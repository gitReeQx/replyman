from fastapi import APIRouter, Cookie, Header
from typing import Optional, Dict
from app.models.schemas import (
    TrainingStartRequest, TrainingMessage, TrainingResponse,
    TrainingEndRequest, TrainingFeedback
)
from app.services.ai_service import ai_service
from app.services.appwrite_service import appwrite_service
import uuid
import logging
import asyncio

router = APIRouter()
logger = logging.getLogger(__name__)

# In-memory training sessions cache (primary)
training_sessions: Dict[str, dict] = {}

# Sessions from auth module
try:
    from app.routes.auth import sessions
except ImportError:
    sessions = {}


def get_user_id_from_session(session_token: Optional[str] = None, authorization: Optional[str] = None) -> Optional[str]:
    """Get user ID from session (cookie or Authorization header)"""
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    elif session_token:
        token = session_token

    if token and token in sessions:
        return sessions[token].get("user_id")
    return None


async def _save_training_to_appwrite(user_id: str, session_id: str, session: dict):
    """Сохраняет состояние тренировки в Appwrite (фоновая задача, не блокирует ответ)"""
    try:
        data = {
            "session_id": session_id,
            "scenario": session.get("scenario", "general"),
            "context": session.get("context", ""),
            "system_prompt": session.get("system_prompt", ""),
            "conversation": session.get("conversation", []),
            "user_id": user_id
        }
        await appwrite_service.save_active_training(user_id, data)
    except Exception as e:
        logger.warning(f"Failed to save training to Appwrite: {e}")


async def _restore_training_from_appwrite(user_id: str, session_id: str) -> Optional[dict]:
    """Восстанавливает тренировку из Appwrite в память"""
    try:
        data = await appwrite_service.get_active_training(user_id)
        if data and data.get("session_id") == session_id:
            training_sessions[session_id] = {
                "scenario": data.get("scenario", "general"),
                "context": data.get("context", ""),
                "system_prompt": data.get("system_prompt", ""),
                "conversation": data.get("conversation", []),
                "started": True
            }
            return training_sessions[session_id]
    except Exception as e:
        logger.warning(f"Failed to restore training from Appwrite: {e}")
    return None


async def _clear_training_from_appwrite(user_id: str):
    """Удаляет запись об активной тренировке из Appwrite"""
    try:
        await appwrite_service.clear_active_training(user_id)
    except Exception as e:
        logger.warning(f"Failed to clear training from Appwrite: {e}")


# ========================================
# REST endpoints
# ========================================

@router.get("/active")
async def get_active_training(
    session_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None)
):
    """Проверить, есть ли активная тренировка у пользователя"""
    user_id = get_user_id_from_session(session_token, authorization)
    if not user_id:
        return {"success": False, "message": "Не авторизован", "active": False}

    try:
        data = await appwrite_service.get_active_training(user_id)
        if not data:
            return {"success": True, "active": False}

        session_id = data.get("session_id", "")
        # Восстанавливаем в память если нет
        if session_id not in training_sessions:
            session = await _restore_training_from_appwrite(user_id, session_id)
            if not session:
                return {"success": True, "active": False}

        return {
            "success": True,
            "active": True,
            "session_id": session_id,
            "scenario": data.get("scenario", "general"),
            "conversation": data.get("conversation", [])
        }
    except Exception as e:
        logger.error(f"get_active_training error: {e}")
        return {"success": False, "active": False, "message": str(e)}


@router.post("/start")
async def start_training(
    request: TrainingStartRequest,
    session_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None)
):
    """Start a new training session"""

    user_id = get_user_id_from_session(session_token, authorization)
    if not user_id:
        return TrainingResponse(success=False, message="Не авторизован")

    # Create new session
    session_id = str(uuid.uuid4())

    # Get context from knowledge base (users.knowledge)
    context = ""
    try:
        context = await appwrite_service.get_user_knowledge(user_id)
        logger.info(f"Training: loaded {len(context)} chars of knowledge for {user_id}")
    except Exception as e:
        logger.warning(f"Training: failed to load knowledge: {e}")

    # Build training prompt
    system_prompt = ai_service.build_training_prompt(request.scenario, context)

    # Initialize session
    training_sessions[session_id] = {
        "scenario": request.scenario,
        "context": context,
        "system_prompt": system_prompt,
        "conversation": [],
        "started": True
    }

    # Get initial message from AI (as client)
    initial_message = await ai_service.chat_completion(
        messages=[{"role": "user", "content": "Начни диалог с клиентом. Представься как потенциальный клиент, который интересуется продукцией. Будь естественным."}],
        system_prompt=system_prompt,
        temperature=0.8
    )

    training_sessions[session_id]["conversation"].append({
        "role": "user",  # AI plays client, so it's "user" in the conversation
        "content": initial_message
    })

    # Сохраняем в Appwrite (неблокирующе)
    asyncio.create_task(_save_training_to_appwrite(user_id, session_id, training_sessions[session_id]))

    return TrainingResponse(
        success=True,
        message="Тренировка началась. ИИ играет роль клиента.",
        response=initial_message,
        role="client",
        session_id=session_id
    )


@router.post("/message", response_model=TrainingResponse)
async def send_training_message(
    request: TrainingMessage,
    session_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None)
):
    """Send a message during training"""

    user_id = get_user_id_from_session(session_token, authorization)
    session_id = request.session_id

    # Если сессии нет в памяти — пробуем восстановить из Appwrite
    if session_id not in training_sessions and user_id:
        await _restore_training_from_appwrite(user_id, session_id)

    if session_id not in training_sessions:
        return TrainingResponse(
            success=False,
            message="Сессия тренинга не найдена"
        )

    session = training_sessions[session_id]

    # Add employee's response to conversation (as assistant)
    session["conversation"].append({
        "role": "assistant",
        "content": request.message
    })

    # Get AI response as client
    messages = session["conversation"]

    response_text = await ai_service.chat_completion(
        messages=messages,
        system_prompt=session["system_prompt"],
        temperature=0.8
    )

    # Add client response to conversation
    session["conversation"].append({
        "role": "user",
        "content": response_text
    })

    # Сохраняем в Appwrite (неблокирующе)
    if user_id:
        asyncio.create_task(_save_training_to_appwrite(user_id, session_id, session))

    return TrainingResponse(
        success=True,
        message="",
        response=response_text,
        role="client",
        session_id=session_id
    )


@router.post("/end", response_model=TrainingFeedback)
async def end_training(
    request: TrainingEndRequest,
    session_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None)
):
    """End training session and get feedback"""

    user_id = get_user_id_from_session(session_token, authorization)
    session_id = request.session_id

    # Если сессии нет в памяти — пробуем восстановить из Appwrite
    if session_id not in training_sessions and user_id:
        await _restore_training_from_appwrite(user_id, session_id)

    if session_id not in training_sessions:
        return TrainingFeedback(
            success=False,
            full_feedback="Сессия тренинга не найдена"
        )

    session = training_sessions[session_id]
    conversation = session["conversation"]

    # Generate feedback
    feedback = await ai_service.generate_training_feedback(
        conversation=conversation,
        chat_history=session["context"]
    )

    # Clean up session from memory
    del training_sessions[session_id]

    # Clean up session from Appwrite
    if user_id:
        await _clear_training_from_appwrite(user_id)

    # Инкрементируем счётчик тренировок
    if user_id:
        try:
            await appwrite_service.increment_user_stat(user_id, "trainings_count")
        except Exception as e:
            logger.warning(f"Failed to increment trainings_count: {e}")

    return TrainingFeedback(
        success=True,
        overall_score=feedback.get("overall_score", 0),
        strengths=feedback.get("strengths", []),
        weaknesses=feedback.get("weaknesses", []),
        recommendations=feedback.get("recommendations", []),
        full_feedback=feedback.get("full_feedback", "")
    )


@router.get("/scenarios")
async def get_scenarios():
    """Get available training scenarios"""
    return {
        "success": True,
        "scenarios": [
            {
                "id": "general",
                "name": "Общение с клиентом",
                "description": "Типичные вопросы о продукции и услугах"
            },
            {
                "id": "sales",
                "name": "Продажи",
                "description": "Работа с возражениями и завершение сделки"
            },
            {
                "id": "support",
                "name": "Техподдержка",
                "description": "Решение проблем и ответы на жалобы"
            },
            {
                "id": "installation",
                "name": "Монтаж",
                "description": "Вопросы по установке и измерению"
            }
        ]
    }

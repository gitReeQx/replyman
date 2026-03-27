from fastapi import APIRouter, Cookie
from typing import Optional, Dict
from app.models.schemas import (
    TrainingStartRequest, TrainingMessage, TrainingResponse,
    TrainingEndRequest, TrainingFeedback
)
from app.services.ai_service import ai_service
from app.services.appwrite_service import appwrite_service
from app.services.file_processor import file_processor
import uuid
import os

router = APIRouter()

# In-memory training sessions storage
training_sessions: Dict[str, dict] = {}

# Local file storage reference
LOCAL_STORAGE_PATH = "/tmp/replyman_files"
LOCAL_FILES_DB = {}

def get_user_id_from_session(session_token: Optional[str]) -> str:
    """Get user ID from session or return default"""
    return "dev_user"

@router.post("/start")
async def start_training(
    request: TrainingStartRequest,
    session_token: Optional[str] = Cookie(None)
):
    """Start a new training session"""
    
    user_id = get_user_id_from_session(session_token)
    
    # Create new session
    session_id = str(uuid.uuid4())
    
    # Get context from files
    context_parts = []
    
    # Get local files
    user_files = LOCAL_FILES_DB.get(user_id, [])
    for f in user_files:
        file_path = os.path.join(LOCAL_STORAGE_PATH, f["id"])
        if os.path.exists(file_path):
            with open(file_path, "rb") as file:
                content = file.read()
            result = await file_processor.process_file(
                content,
                f.get("content_type", "text/plain"),
                f.get("name", "")
            )
            if result.get("success"):
                context_parts.append(result.get("content", ""))
    
    # Also try Appwrite
    try:
        files = await appwrite_service.get_user_files(user_id)
        for f in files:
            file_id = f.get("file_id")
            if file_id:
                content = await appwrite_service.get_file_content(file_id)
                if content:
                    result = await file_processor.process_file(
                        content,
                        f.get("content_type", "text/plain"),
                        f.get("file_name", "")
                    )
                    if result.get("success"):
                        context_parts.append(result.get("content", ""))
    except Exception:
        pass
    
    context = "\n\n".join(context_parts)
    
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
    session_token: Optional[str] = Cookie(None)
):
    """Send a message during training"""
    
    session_id = request.session_id
    
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
    session_token: Optional[str] = Cookie(None)
):
    """End training session and get feedback"""
    
    session_id = request.session_id
    
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
    
    # Clean up session
    del training_sessions[session_id]
    
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

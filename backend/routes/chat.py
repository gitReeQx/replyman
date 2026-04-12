"""
Routes для чата - ИСПРАВЛЕННАЯ ВЕРСИЯ
Контекст берётся из users.knowledge (не из файлов)
+ Проверка дневного лимита запросов по тарифу
"""
from fastapi import APIRouter, Cookie, Header, Request
from typing import Optional, Dict
from app.models.schemas import ChatRequest, ChatResponse
from app.services.appwrite_service import appwrite_service
from app.services.ai_service import ai_service
import uuid
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

# In-memory session storage
chat_sessions: Dict[str, list] = {}

# Лимиты запросов по тарифам
TARIFF_DAILY_LIMITS = {
    "бесплатный": 3,
    "старт": 20,
    "бизнес": None,  # без ограничений
}

# Sessions from auth module
try:
    from app.routes.auth import sessions
except ImportError:
    sessions = {}


def get_user_id(
    session_token: Optional[str] = None,
    request: Optional[Request] = None,
    authorization: Optional[str] = None
) -> Optional[str]:
    """Получить ID пользователя из сессии (cookie или Authorization header)"""
    token = None
    # Сначала пробуем Authorization header
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    # Затем cookie
    elif session_token:
        token = session_token
    # Затем request.cookies (если передан request)
    elif request:
        token = request.cookies.get("session_token")
    
    if token and token in sessions:
        return sessions[token].get("user_id")
    return None


@router.post("/message", response_model=ChatResponse)
async def send_message(
    request: ChatRequest,
    session_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
    fastapi_request: Request = None  # добавить для возможности получить request
):
    uid = get_user_id(session_token, fastapi_request, authorization)
    if not uid:
        return ChatResponse(success=False, message="Не авторизован", response="", session_id="")
    
    # ========== Проверка дневного лимита запросов ==========
    try:
        sub = await appwrite_service.get_user_subscription(uid)
        tariff_id = sub.get("subscription_type", "бесплатный")
        daily_limit = TARIFF_DAILY_LIMITS.get(tariff_id, 3)
        
        if daily_limit is not None:  # None = без ограничений (бизнес)
            daily_count = await appwrite_service.get_daily_request_count(uid)
            if daily_count >= daily_limit:
                limit_msg = f"Лимит {daily_limit} запросов в день исчерпан. "
                if tariff_id == "бесплатный":
                    limit_msg += "Оплатите тариф, чтобы получить больше запросов."
                else:
                    limit_msg += "Повысьте тариф для большего количества."
                return ChatResponse(
                    success=False,
                    message=limit_msg,
                    response="",
                    session_id=request.session_id or ""
                )
    except Exception as e:
        logger.warning(f"Failed to check daily limit: {e}")
        # Не блокируем чат, если проверка не удалась — пропускаем
    logger.info(f"=== CHAT from user: {uid} ===")
    print(f"=== CHAT: use_context={request.use_context}, uid={uid} ===")
    
    # Получаем или создаём сессию
    session_id = request.session_id or str(uuid.uuid4())
    
    if session_id not in chat_sessions:
        chat_sessions[session_id] = []
    
    # Добавляем сообщение пользователя
    chat_sessions[session_id].append({
        "role": "user",
        "content": request.message
    })
    
    # ========== КОНТЕКСТ ИЗ users.knowledge ==========
    knowledge = ""
    custom_instructions = ""
    
    if request.use_context:
        try:
            knowledge = await appwrite_service.get_user_knowledge(uid)
            print(f"=== CHAT: knowledge size={len(knowledge)} ===")
            logger.info(f"Knowledge loaded: {len(knowledge)} chars for user {uid}")
        except Exception as e:
            print(f"=== CHAT: error loading knowledge: {e}")
            logger.warning(f"Could not load knowledge: {e}")
            knowledge = ""
        
        try:
            custom_instructions = await appwrite_service.get_user_instructions(uid)
        except Exception:
            pass
    else:
        print("=== CHAT: use_context is False, not loading knowledge ===")
    
    # Строим system prompt
    system_prompt = build_system_prompt(knowledge, custom_instructions)
    print(f"=== CHAT: system_prompt length={len(system_prompt)}, includes knowledge? {bool(knowledge)}")
    
    # Получаем историю сообщений
    messages = chat_sessions[session_id]
    
    # Отправляем в AI
    response_text = await ai_service.chat_completion(
        messages=messages,
        system_prompt=system_prompt,
        temperature=0.7
    )
    
    # Добавляем ответ ассистента
    chat_sessions[session_id].append({
        "role": "assistant",
        "content": response_text
    })
    
    # Инкрементируем счётчик сообщений и дневной лимит запросов
    try:
        from app.services.appwrite_service import appwrite_service as _as
        await _as.increment_user_stat(uid, "messages_count")
        await _as.increment_daily_request_count(uid)
    except Exception as e:
        print(f"Failed to increment messages_count: {e}")
    
    logger.info(f"Response: {len(response_text)} chars")
    
    return ChatResponse(
        success=True,
        message="Ответ получен",
        response=response_text,
        session_id=session_id
    )


def build_system_prompt(knowledge: str, custom_instructions: str = "") -> str:
    return ai_service.build_context_prompt(knowledge, custom_instructions)


@router.get("/history/{session_id}")
async def get_chat_history(session_id: str):
    """Получить историю чата"""
    
    if session_id in chat_sessions:
        return {
            "success": True,
            "history": chat_sessions[session_id]
        }
    else:
        return {
            "success": False,
            "message": "Сессия не найдена"
        }


@router.delete("/session/{session_id}")
async def clear_session(session_id: str):
    """Очистить сессию чата"""
    
    if session_id in chat_sessions:
        del chat_sessions[session_id]
    
    return {"success": True, "message": "Сессия очищена"}


@router.post("/new-session")
async def create_new_session():
    """Создать новую сессию чата"""
    
    session_id = str(uuid.uuid4())
    chat_sessions[session_id] = []
    
    return {
        "success": True,
        "session_id": session_id
    }

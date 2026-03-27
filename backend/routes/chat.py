from fastapi import APIRouter, Cookie
from typing import Optional, List, Dict
from app.models.schemas import ChatRequest, ChatResponse
from app.services.ai_service import ai_service
from app.services.appwrite_service import appwrite_service
from app.services.file_processor import file_processor
import uuid
import os

router = APIRouter()

# In-memory session storage (in production use Redis or database)
chat_sessions: Dict[str, List[Dict[str, str]]] = {}

# Import local file storage from files router
LOCAL_STORAGE_PATH = "/tmp/replyman_files"
LOCAL_FILES_DB = {}

def get_user_id_from_session(session_token: Optional[str]) -> str:
    """Get user ID from session or return default"""
    return "dev_user"

@router.post("/message", response_model=ChatResponse)
async def send_message(
    request: ChatRequest,
    session_token: Optional[str] = Cookie(None)
):
    """Send a message to AI assistant"""
    
    user_id = get_user_id_from_session(session_token)
    
    # Get or create session
    session_id = request.session_id or str(uuid.uuid4())
    
    if session_id not in chat_sessions:
        chat_sessions[session_id] = []
    
    # Add user message to history
    chat_sessions[session_id].append({
        "role": "user",
        "content": request.message
    })
    
    # Build context from uploaded files
    context = ""
    custom_instructions = ""
    
    if request.use_context:
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
        
        # Get custom instructions
        try:
            custom_instructions = await appwrite_service.get_user_instructions(user_id)
        except Exception:
            pass
    
    # Build system prompt
    system_prompt = ai_service.build_context_prompt(context, custom_instructions)
    
    # Get AI response
    messages = chat_sessions[session_id]
    
    response_text = await ai_service.chat_completion(
        messages=messages,
        system_prompt=system_prompt,
        temperature=0.7
    )
    
    # Add assistant response to history
    chat_sessions[session_id].append({
        "role": "assistant",
        "content": response_text
    })
    
    return ChatResponse(
        success=True,
        message="Ответ получен",
        response=response_text,
        session_id=session_id
    )

@router.get("/history/{session_id}")
async def get_chat_history(session_id: str):
    """Get chat history for a session"""
    
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
    """Clear chat session"""
    
    if session_id in chat_sessions:
        del chat_sessions[session_id]
    
    return {"success": True, "message": "Сессия очищена"}

@router.post("/new-session")
async def create_new_session():
    """Create a new chat session"""
    
    session_id = str(uuid.uuid4())
    chat_sessions[session_id] = []
    
    return {
        "success": True,
        "session_id": session_id
    }

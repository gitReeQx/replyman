from fastapi import APIRouter, Cookie, Header
from typing import Optional
from app.models.schemas import InstructionsUpdate, InstructionsResponse
from app.services.appwrite_service import appwrite_service

router = APIRouter()

# Local storage for instructions (for development)
LOCAL_INSTRUCTIONS = {}

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

@router.get("", response_model=InstructionsResponse)
async def get_instructions(session_token: Optional[str] = Cookie(None), authorization: Optional[str] = Header(None)):
    """Get user's custom instructions"""
    
    user_id = get_user_id_from_session(session_token, authorization)
    if not user_id:
        return InstructionsResponse(success=False, message="Не авторизован", instructions="")
    
    # Try Appwrite first
    try:
        instructions = await appwrite_service.get_user_instructions(user_id)
        if instructions:
            return InstructionsResponse(
                success=True,
                message="Инструкции получены",
                instructions=instructions
            )
    except Exception as e:
        print(f"Appwrite get instructions failed: {e}")
    
    # Fallback: local storage
    instructions = LOCAL_INSTRUCTIONS.get(user_id, "")
    
    return InstructionsResponse(
        success=True,
        message="Инструкции получены",
        instructions=instructions
    )

@router.post("", response_model=InstructionsResponse)
async def update_instructions(
    request: InstructionsUpdate,
    session_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None)
):
    """Update user's custom instructions"""
    
    user_id = get_user_id_from_session(session_token, authorization)
    if not user_id:
        return InstructionsResponse(success=False, message="Не авторизован", instructions="")
    
    # Try Appwrite first
    try:
        result = await appwrite_service.save_user_instructions(user_id, request.instructions)
        if result.get("success"):
            return InstructionsResponse(
                success=True,
                message="Инструкции сохранены",
                instructions=request.instructions
            )
    except Exception as e:
        print(f"Appwrite save instructions failed: {e}")
    
    # Fallback: local storage
    LOCAL_INSTRUCTIONS[user_id] = request.instructions
    
    return InstructionsResponse(
        success=True,
        message="Инструкции сохранены",
        instructions=request.instructions
    )

@router.delete("")
async def reset_instructions(session_token: Optional[str] = Cookie(None), authorization: Optional[str] = Header(None)):
    """Reset user's custom instructions"""
    
    user_id = get_user_id_from_session(session_token, authorization)
    if not user_id:
        return {"success": False, "message": "Не авторизован"}
    
    # Try Appwrite first
    try:
        result = await appwrite_service.save_user_instructions(user_id, "")
    except Exception:
        pass
    
    # Also clear local storage
    if user_id in LOCAL_INSTRUCTIONS:
        del LOCAL_INSTRUCTIONS[user_id]
    
    return {"success": True, "message": "Инструкции сброшены"}

from fastapi import APIRouter, Cookie
from typing import Optional
from app.models.schemas import InstructionsUpdate, InstructionsResponse
from app.services.appwrite_service import appwrite_service

router = APIRouter()

# Local storage for instructions (for development)
LOCAL_INSTRUCTIONS = {}

def get_user_id_from_session(session_token: Optional[str]) -> str:
    """Get user ID from session or return default"""
    return "dev_user"

@router.get("", response_model=InstructionsResponse)
async def get_instructions(session_token: Optional[str] = Cookie(None)):
    """Get user's custom instructions"""
    
    user_id = get_user_id_from_session(session_token)
    
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
    session_token: Optional[str] = Cookie(None)
):
    """Update user's custom instructions"""
    
    user_id = get_user_id_from_session(session_token)
    
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
async def reset_instructions(session_token: Optional[str] = Cookie(None)):
    """Reset user's custom instructions"""
    
    user_id = get_user_id_from_session(session_token)
    
    # Try Appwrite first
    try:
        result = await appwrite_service.save_user_instructions(user_id, "")
    except Exception:
        pass
    
    # Also clear local storage
    if user_id in LOCAL_INSTRUCTIONS:
        del LOCAL_INSTRUCTIONS[user_id]
    
    return {"success": True, "message": "Инструкции сброшены"}

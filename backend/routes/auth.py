from fastapi import APIRouter, HTTPException, Header, Cookie, Response, Request
from typing import Optional
from app.models.schemas import UserRegister, UserLogin, AuthResponse, UserResponse
from app.services.appwrite_service import appwrite_service
import secrets
import hashlib
from datetime import datetime

router = APIRouter()

# Simple in-memory session storage (use Redis in production)
sessions = {}

# Simple in-memory user storage for development without Appwrite
users_db = {}

def hash_password(password: str) -> str:
    """Hash password for storage"""
    return hashlib.sha256(password.encode()).hexdigest()

def generate_session_token() -> str:
    """Generate a secure session token"""
    return secrets.token_urlsafe(32)

def get_token_from_header(authorization: Optional[str] = None) -> Optional[str]:
    """Extract token from Authorization header"""
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    return None

def get_session_token(
    session_token_cookie: Optional[str] = None,
    authorization: Optional[str] = None
) -> Optional[str]:
    """Get session token from cookie or Authorization header"""
    # First try Authorization header (for cross-domain)
    token = get_token_from_header(authorization)
    if token:
        return token
    # Fallback to cookie
    return session_token_cookie


@router.post("/register", response_model=AuthResponse)
async def register(user_data: UserRegister):
    """Register a new user"""
    
    # Check if user already exists locally
    if user_data.email in users_db:
        return AuthResponse(
            success=False,
            message="Пользователь с таким email уже существует"
        )
    
    try:
        # Try Appwrite registration first
        result = await appwrite_service.create_user(
            email=user_data.email,
            password=user_data.password,
            name=user_data.name
        )
        
        if result.get("success"):
            user = result["user"]
            return AuthResponse(
                success=True,
                message="Пользователь успешно зарегистрирован",
                user=UserResponse(
                    id=user.get("$id", ""),
                    email=user.get("email", user_data.email),
                    name=user.get("name", user_data.name),
                    created_at=datetime.now()
                )
            )
    except Exception as e:
        print(f"Appwrite registration failed: {e}")
    
    # Fallback: local registration (for development)
    user_id = secrets.token_urlsafe(16)
    users_db[user_data.email] = {
        "id": user_id,
        "email": user_data.email,
        "name": user_data.name or user_data.email.split("@")[0],
        "password_hash": hash_password(user_data.password),
        "created_at": datetime.now()
    }
    
    return AuthResponse(
        success=True,
        message="Пользователь успешно зарегистрирован",
        user=UserResponse(
            id=user_id,
            email=user_data.email,
            name=user_data.name or user_data.email.split("@")[0],
            created_at=datetime.now()
        )
    )


@router.post("/login", response_model=AuthResponse)
async def login(user_data: UserLogin, response: Response):
    """Login user and create session"""
    
    try:
        # Try Appwrite login first
        result = await appwrite_service.create_session(
            email=user_data.email,
            password=user_data.password
        )
        
        print(f"Login result: {result}")
        
        if result.get("success"):
            session = result.get("session", {})
            user_info = result.get("user", {})
            user_id = user_info.get("$id", "") or session.get("userId", "")
            
            # Generate our own session token
            session_token = generate_session_token()
            
            print(f"Generated session_token: {session_token[:20]}...")
            print(f"User ID: {user_id}")
            
            # Save session to memory
            sessions[session_token] = {
                "user_id": user_id,
                "email": user_data.email,
                "name": user_info.get("name", ""),
                "created_at": datetime.now(),
                "appwrite_session_id": session.get("$id", "")
            }
            
            print(f"Sessions dict: {list(sessions.keys())}")
            
            return AuthResponse(
                success=True,
                message="Успешный вход",
                session_token=session_token,
                user=UserResponse(
                    id=user_id,
                    email=user_data.email,
                    name=user_info.get("name", ""),
                    created_at=datetime.now()
                )
            )
        else:
            print(f"Login failed: {result.get('error')}")
    except Exception as e:
        print(f"Appwrite login exception: {e}")
        import traceback
        traceback.print_exc()
    
    # Fallback: local login (for development)
    user = users_db.get(user_data.email)
    
    if not user:
        return AuthResponse(
            success=False,
            message="Пользователь не найден"
        )
    
    if user["password_hash"] != hash_password(user_data.password):
        return AuthResponse(
            success=False,
            message="Неверный пароль"
        )
    
    # Create session
    session_token = generate_session_token()
    sessions[session_token] = {
        "user_id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "created_at": datetime.now()
    }
    
    return AuthResponse(
        success=True,
        message="Успешный вход",
        session_token=session_token,
        user=UserResponse(
            id=user["id"],
            email=user["email"],
            name=user["name"],
            created_at=user["created_at"]
        )
    )


@router.post("/logout")
async def logout(
    response: Response,
    session_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None)
):
    """Logout user and delete session"""
    
    # Get token from header or cookie
    token = get_session_token(session_token, authorization)
    
    # Try Appwrite logout
    try:
        await appwrite_service.delete_session()
    except Exception:
        pass
    
    # Remove local session
    if token and token in sessions:
        del sessions[token]
    
    return {"success": True, "message": "Вы успешно вышли из системы"}


@router.get("/me", response_model=AuthResponse)
async def get_current_user(
    session_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None)
):
    """Get current authenticated user"""
    
    # Get token from header or cookie
    token = get_session_token(session_token, authorization)
    
    print(f"get_current_user called, token: {token[:20] if token else 'None'}...")
    print(f"Sessions in memory: {list(sessions.keys())}")
    
    if not token:
        return AuthResponse(
            success=False,
            message="Не авторизован"
        )
    
    # Check local session
    if token in sessions:
        session = sessions[token]
        print(f"Found session: {session}")
        return AuthResponse(
            success=True,
            message="Пользователь найден",
            user=UserResponse(
                id=session["user_id"],
                email=session["email"],
                name=session["name"],
                created_at=session.get("created_at")
            )
        )
    
    print(f"Session not found in memory!")
    
    return AuthResponse(
        success=False,
        message="Сессия недействительна"
    )


@router.get("/stats")
async def get_user_stats(
    session_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None)
):
    """Get user stats: files_count, messages_count, trainings_count, subscription_type"""
    
    token = get_session_token(session_token, authorization)
    
    if not token or token not in sessions:
        return {"success": False, "message": "Не авторизован"}
    
    session = sessions[token]
    user_id = session.get("user_id", "")
    
    if not user_id:
        return {"success": False, "message": "User ID not found"}
    
    try:
        from app.services.appwrite_service import appwrite_service
        stats = await appwrite_service.get_user_stats(user_id)
        return stats
    except Exception as e:
        return {
            "success": False,
            "message": str(e),
            "files_count": 0,
            "messages_count": 0,
            "trainings_count": 0,
            "subscription_type": "старт"
        }


@router.get("/verify")
async def verify_session(
    session_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None)
):
    """Verify if session is valid"""
    
    # Get token from header or cookie
    token = get_session_token(session_token, authorization)
    
    if not token:
        return {"valid": False}
    
    # Check local session
    if token in sessions:
        return {"valid": True}
    
    return {"valid": False}
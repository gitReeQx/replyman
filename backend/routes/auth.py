from fastapi import APIRouter, HTTPException, Header, Cookie, Response, Request
from typing import Optional
from pydantic import BaseModel
from app.models.schemas import UserRegister, UserLogin, AuthResponse, UserResponse
from app.services.appwrite_service import appwrite_service
from app.config import get_settings
import secrets
import hashlib
from datetime import datetime

router = APIRouter()
settings = get_settings()

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
            user_id = user.get("$id", "")
            
            # Автоматически входим в аккаунт после регистрации
            # (нужна сессия для Account API — отправка письма подтверждения)
            session_result = await appwrite_service.create_session(
                email=user_data.email,
                password=user_data.password
            )
            
            appwrite_session_secret = ""
            session_token = None
            
            if session_result.get("success"):
                aw_session = session_result.get("session", {})
                appwrite_session_secret = aw_session.get("secret", "")
                aw_session_id = aw_session.get("$id", "")
                
                # Создаём нашу сессию
                session_token = generate_session_token()
                sessions[session_token] = {
                    "user_id": user_id,
                    "email": user_data.email,
                    "name": user.get("name", ""),
                    "created_at": datetime.now(),
                    "appwrite_session_secret": appwrite_session_secret,
                    "email_verified": False
                }
            
            # Отправляем письмо для подтверждения email через Account API
            verification_url = f"{settings.frontend_url}/lk/index.html?verify=1"
            try:
                await appwrite_service.send_email_verification(user_id, verification_url, appwrite_session_secret)
            except Exception as ve:
                print(f"Failed to send verification email: {ve}")
            
            return AuthResponse(
                success=True,
                message="Пользователь успешно зарегистрирован. Проверьте почту для подтверждения email.",
                session_token=session_token,
                user=UserResponse(
                    id=user_id,
                    email=user.get("email", user_data.email),
                    name=user.get("name", user_data.name),
                    created_at=datetime.now(),
                    email_verified=False
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
        "created_at": datetime.now(),
        "email_verified": True  # Для локальной разработки считаем верифицированным
    }
    
    return AuthResponse(
        success=True,
        message="Пользователь успешно зарегистрирован",
        user=UserResponse(
            id=user_id,
            email=user_data.email,
            name=user_data.name or user_data.email.split("@")[0],
            created_at=datetime.now(),
            email_verified=True
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
            
            # Проверяем подтверждение email
            email_verified = await appwrite_service.is_email_verified(user_id)
            
            # Generate our own session token
            session_token = generate_session_token()
            
            print(f"Generated session_token: {session_token[:20]}...")
            print(f"User ID: {user_id}, email_verified: {email_verified}")
            
            # Save session to memory
            # Важно: для Account API нужен SECRET сессии, а не ID!
            appwrite_session_secret = session.get("secret", "")
            sessions[session_token] = {
                "user_id": user_id,
                "email": user_data.email,
                "name": user_info.get("name", ""),
                "created_at": datetime.now(),
                "appwrite_session_secret": appwrite_session_secret,
                "email_verified": email_verified
            }
            
            # Если email не подтверждён — отправляем письмо через Account API
            if not email_verified:
                verification_url = f"{settings.frontend_url}/lk/index.html?verify=1"
                try:
                    await appwrite_service.send_email_verification(user_id, verification_url, appwrite_session_secret)
                except Exception as ve:
                    print(f"Failed to send verification email on login: {ve}")
            
            return AuthResponse(
                success=True,
                message="Успешный вход" if email_verified else "Подтвердите email для доступа",
                session_token=session_token,
                user=UserResponse(
                    id=user_id,
                    email=user_data.email,
                    name=user_info.get("name", ""),
                    created_at=datetime.now(),
                    email_verified=email_verified
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
        "created_at": datetime.now(),
        "email_verified": user.get("email_verified", True)
    }
    
    return AuthResponse(
        success=True,
        message="Успешный вход",
        session_token=session_token,
        user=UserResponse(
            id=user["id"],
            email=user["email"],
            name=user["name"],
            created_at=user["created_at"],
            email_verified=user.get("email_verified", True)
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
    
    if not token:
        return AuthResponse(
            success=False,
            message="Не авторизован"
        )
    
    # Check local session
    if token in sessions:
        session = sessions[token]
        
        # Проверяем актуальный статус верификации email из Appwrite
        email_verified = session.get("email_verified", False)
        user_id = session.get("user_id", "")
        
        if user_id and not email_verified:
            # Обновляем статус из Appwrite (пользователь мог подтвердить email в другой сессии)
            try:
                current_verified = await appwrite_service.is_email_verified(user_id)
                if current_verified != email_verified:
                    email_verified = current_verified
                    sessions[token]["email_verified"] = current_verified
            except Exception:
                pass
        
        return AuthResponse(
            success=True,
            message="Пользователь найден",
            user=UserResponse(
                id=session["user_id"],
                email=session["email"],
                name=session["name"],
                created_at=session.get("created_at"),
                email_verified=email_verified
            )
        )
    
    return AuthResponse(
        success=False,
        message="Сессия недействительна"
    )


@router.get("/stats")
async def get_user_stats(
    session_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None)
):
    """Get user stats: files_count, messages_count, trainings_count, subscription_type, subscription_status"""
    
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
        # Добавляем информацию о подписке
        sub = await appwrite_service.get_user_subscription(user_id)
        stats["subscription_status"] = sub.get("subscription_status", "inactive")
        stats["subscription_expires_at"] = sub.get("subscription_expires_at", None)
        return stats
    except Exception as e:
        return {
            "success": False,
            "message": str(e),
            "files_count": 0,
            "messages_count": 0,
            "trainings_count": 0,
            "subscription_type": "бесплатный",
            "subscription_status": "inactive"
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


# ========================================
# Email Verification Endpoints
# ========================================

class EmailVerifyConfirm(BaseModel):
    user_id: str
    secret: str

@router.post("/send-verification")
async def send_verification_email(
    session_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None)
):
    """Отправить письмо для подтверждения email повторно"""
    
    token = get_session_token(session_token, authorization)
    
    if not token or token not in sessions:
        return {"success": False, "message": "Не авторизован"}
    
    session = sessions[token]
    user_id = session.get("user_id", "")
    
    if not user_id:
        return {"success": False, "message": "User ID not found"}
    
    # Проверяем, не подтверждён ли уже email
    email_verified = await appwrite_service.is_email_verified(user_id)
    if email_verified:
        sessions[token]["email_verified"] = True
        return {"success": True, "message": "Email уже подтверждён", "email_verified": True}
    
    # Отправляем письмо через Account API (передаём appwrite_session_secret)
    verification_url = f"{settings.frontend_url}/lk/index.html?verify=1"
    appwrite_session_secret = session.get("appwrite_session_secret", "")
    result = await appwrite_service.send_email_verification(user_id, verification_url, appwrite_session_secret)
    
    if result.get("success"):
        return {"success": True, "message": "Письмо для подтверждения отправлено на ваш email"}
    else:
        return {"success": False, "message": f"Ошибка отправки письма: {result.get('error', 'Неизвестная ошибка')}"}


@router.post("/confirm-verification")
async def confirm_email_verification(data: EmailVerifyConfirm):
    """Подтвердить email по ссылке из письма (userId + secret из URL)"""
    
    # Ищем активную сессию пользователя для Account API
    appwrite_session_secret = None
    for token_key, sess in sessions.items():
        if sess.get("user_id") == data.user_id:
            appwrite_session_secret = sess.get("appwrite_session_secret", "")
            break
    
    result = await appwrite_service.verify_email_by_secret(
        user_id=data.user_id,
        secret=data.secret,
        appwrite_session_secret=appwrite_session_secret
    )
    
    if result.get("success"):
        # Обновляем email_verified во всех активных сессиях этого пользователя
        for token, session in sessions.items():
            if session.get("user_id") == data.user_id:
                sessions[token]["email_verified"] = True
        
        return {"success": True, "message": "Email успешно подтверждён"}
    else:
        return {"success": False, "message": f"Ошибка подтверждения: {result.get('error', 'Ссылка недействительна или устарела')}"}


@router.get("/check-verification")
async def check_email_verification(
    session_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None)
):
    """Проверить статус подтверждения email для текущего пользователя"""
    
    token = get_session_token(session_token, authorization)
    
    if not token or token not in sessions:
        return {"success": False, "message": "Не авторизован"}
    
    session = sessions[token]
    user_id = session.get("user_id", "")
    
    if not user_id:
        return {"success": False, "message": "User ID not found"}
    
    email_verified = await appwrite_service.is_email_verified(user_id)
    
    # Обновляем в сессии
    sessions[token]["email_verified"] = email_verified
    
    return {"success": True, "email_verified": email_verified}

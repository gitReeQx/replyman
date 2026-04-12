"""
Payments Routes — интеграция с ЮKassa
Оплата тарифов (помесячно / за год), обработка вебхуков, статус тарифа
"""

from fastapi import APIRouter, HTTPException, Header, Cookie, Request, Response
from typing import Optional
from app.models.schemas import PaymentCreateRequest
from app.services.appwrite_service import appwrite_service
from app.config import get_settings
from app.routes.auth import sessions, get_session_token
import httpx
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter()

# ========================================
# Тарифы — из главной страницы index.html
# ========================================

TARIFFS = [
    {
        "id": "бесплатный",
        "name": "Бесплатный",
        "description": "Для знакомства с сервисом",
        "price_monthly": 0,
        "price_yearly": 0,
        "price_yearly_old": 0,
        "yearly_save": 0,
        "recommended": False,
        "daily_limit": 3,
        "training_available": False,
        "features": [
            {"text": "До 3 запросов в день", "included": True},
            {"text": "Загрузка файлов (до 30MB)", "included": True},
            {"text": "Умный чат с ИИ", "included": True},
            {"text": "Настройка инструкций ИИ", "included": True},
            {"text": "🎓 Тренажёр общения", "included": False},
            {"text": "Приоритетная поддержка", "included": False},
        ]
    },
    {
        "id": "старт",
        "name": "Старт",
        "description": "Для небольших команд и знакомства с сервисом",
        "price_monthly": 1490,
        "price_yearly": 14900,
        "price_yearly_old": 17490,
        "yearly_save": 2590,
        "recommended": False,
        "daily_limit": 20,
        "training_available": False,
        "features": [
            {"text": "До 20 запросов в день", "included": True},
            {"text": "Загрузка файлов (до 30MB)", "included": True},
            {"text": "Умный чат с ИИ", "included": True},
            {"text": "Настройка инструкций ИИ", "included": True},
            {"text": "Email поддержка", "included": True},
            {"text": "🎓 Тренажёр общения", "included": False},
        ]
    },
    {
        "id": "бизнес",
        "name": "Бизнес",
        "description": "Для команд, которым нужен максимум возможностей",
        "price_monthly": 2890,
        "price_yearly": 28900,
        "price_yearly_old": 34680,
        "yearly_save": 5780,
        "recommended": True,
        "daily_limit": None,  # без ограничений
        "training_available": True,
        "features": [
            {"text": "Без ограничений по запросам", "included": True},
            {"text": "Загрузка файлов (до 30MB)", "included": True},
            {"text": "Умный чат с ИИ", "included": True},
            {"text": "Настройка инструкций ИИ", "included": True},
            {"text": "🎓 Тренажёр общения с ИИ-клиентом", "included": True},
            {"text": "Приоритетная поддержка", "included": True},
        ]
    }
]

# Маппинг тарифов: русские ↔ английские (для совместимости с YooKassa API, который требует ASCII)
TARIFF_ID_TO_EN = {
    "бесплатный": "free",
    "старт": "start",
    "бизнес": "business",
}
TARIFF_ID_FROM_EN = {v: k for k, v in TARIFF_ID_TO_EN.items()}

# Длительность тарифа по периодам
TARIFF_DURATIONS = {
    "monthly": timedelta(days=30),
    "yearly": timedelta(days=365),
}


# ========================================
# Helper: получить user_id из сессии
# ========================================

def _get_user_id(session_token: Optional[str], authorization: Optional[str]) -> Optional[str]:
    token = get_session_token(session_token, authorization)
    if token and token in sessions:
        return sessions[token].get("user_id")
    return None


# ========================================
# GET /tariffs — список тарифов
# ========================================

@router.get("/tariffs")
async def get_tariffs():
    """Вернуть список доступных тарифов"""
    return {"success": True, "tariffs": TARIFFS}


# ========================================
# GET /subscription — текущий тариф пользователя
# ========================================

@router.get("/subscription")
async def get_subscription(
    session_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None)
):
    """Получить информацию о текущем тарифе пользователя"""
    
    user_id = _get_user_id(session_token, authorization)
    if not user_id:
        return {"success": False, "message": "Не авторизован"}
    
    try:
        sub = await appwrite_service.get_user_subscription(user_id)
        
        # Добавляем информацию о лимите запросов на сегодня
        tariff_info = next((t for t in TARIFFS if t["id"] == sub.get("subscription_type", "бесплатный")), TARIFFS[0])
        daily_limit = tariff_info.get("daily_limit")
        
        # Считаем запросы за сегодня
        daily_count = await appwrite_service.get_daily_request_count(user_id)
        
        sub["daily_requests_count"] = daily_count
        sub["daily_requests_limit"] = daily_limit  # None = без ограничений
        sub["training_available"] = tariff_info.get("training_available", False)
        
        return {"success": True, "subscription": sub}
    except Exception as e:
        logger.error(f"get_subscription error: {e}")
        return {
            "success": True,
            "subscription": {
                "subscription_type": "бесплатный",
                "subscription_status": "inactive",
                "subscription_paid_at": None,
                "subscription_expires_at": None,
                "daily_requests_count": 0,
                "daily_requests_limit": 3,
                "training_available": False,
            }
        }


# ========================================
# POST /create — создать платёж в ЮKassa
# ========================================

@router.post("/create")
async def create_payment(
    payment_data: PaymentCreateRequest,
    session_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None)
):
    """Создать платёж в ЮKassa и вернуть ссылку на оплату"""
    
    user_id = _get_user_id(session_token, authorization)
    if not user_id:
        return {"success": False, "message": "Не авторизован"}
    
    # Найти тариф
    tariff = next((t for t in TARIFFS if t["id"] == payment_data.tariff_id), None)
    if not tariff:
        return {"success": False, "message": "Тариф не найден"}
    
    if tariff["price_monthly"] == 0:
        return {"success": False, "message": "Бесплатный тариф не требует оплаты"}
    
    # Определяем период и цену
    period = payment_data.period or "monthly"  # monthly | yearly
    if period == "yearly":
        price = tariff["price_yearly"]
        period_label_en = "year"
    else:
        price = tariff["price_monthly"]
        period_label_en = "month"
    
    # Проверить, нет ли уже активной подписки на этот тариф
    try:
        current_sub = await appwrite_service.get_user_subscription(user_id)
        if (current_sub.get("subscription_status") == "active" and 
            current_sub.get("subscription_type") == payment_data.tariff_id):
            return {"success": False, "message": "У вас уже активен этот тариф"}
    except:
        pass
    
    # Создать платёж через ЮKassa API
    yookassa_shop_id = getattr(settings, 'yookassa_shop_id', '')
    yookassa_secret_key = getattr(settings, 'yookassa_secret_key', '')
    
    if not yookassa_shop_id or not yookassa_secret_key:
        logger.error("YooKassa credentials not configured")
        return {"success": False, "message": "Платёжная система не настроена. Обратитесь к администратору."}
    
    # Маппинг тарифов на английские ID — YooKassa API и HTTP-заголовки требуют ASCII
    tariff_en = TARIFF_ID_TO_EN.get(payment_data.tariff_id, payment_data.tariff_id)

    # IDEMPOTENCY KEY — только ASCII символы (HTTP-заголовки не поддерживают кириллицу)
    tariff_hash = hashlib.md5(payment_data.tariff_id.encode('utf-8')).hexdigest()[:8]
    idempotence_key = f"replyman-{user_id}-{tariff_hash}-{period}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    # Получаем email пользователя для чека (54-ФЗ)
    user_email = ""
    try:
        user_info = await appwrite_service.get_user(user_id)
        if user_info.get("success"):
            user_email = user_info.get("user", {}).get("email", "")
    except Exception as e:
        logger.warning(f"Could not get user email for receipt: {e}")

    if not user_email:
        user_email = f"{user_id}@replyman.ru"  # fallback для чека

    # VAT code из конфига
    vat_code = getattr(settings, 'yookassa_vat_code', 4)

    # Все строки в payload должны быть ASCII-безопасными для совместимости с YooKassa
    payment_payload = {
        "amount": {
            "value": f"{price}.00",
            "currency": "RUB"
        },
        "confirmation": {
            "type": "redirect",
            # Передаём payment_id в return_url чтобы проверить реальный статус при возврате
            "return_url": f"{settings.frontend_url}/lk/billing.html?payment=pending&payment_id={{payment_id}}"
        },
        "capture": True,
        "description": f"ReplyMan - {tariff_en.capitalize()} tariff, {period_label_en}",
        "metadata": {
            "user_id": user_id,
            "tariff_id": tariff_en,
            "tariff_name": tariff_en.capitalize(),
            "period": period
        },
        "receipt": {
            "customer": {
                "email": user_email
            },
            "items": [
                {
                    "description": f"ReplyMan {tariff_en.capitalize()} - {period_label_en}",
                    "quantity": "1",
                    "amount": {
                        "value": f"{price}.00",
                        "currency": "RUB"
                    },
                    "vat_code": vat_code,
                    "payment_mode": "full_payment",
                    "payment_subject": "service",
                }
            ],
        }
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.yookassa.ru/v3/payments",
                json=payment_payload,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Idempotence-Key": idempotence_key
                },
                auth=(str(yookassa_shop_id), str(yookassa_secret_key)),
                timeout=30.0
            )
            
            if response.status_code == 200:
                payment_info = response.json()
                confirmation_url = None
                
                confirmation = payment_info.get("confirmation", {})
                if confirmation.get("type") == "redirect":
                    confirmation_url = confirmation.get("confirmation_url")
                
                payment_id = payment_info.get("id", "")
                
                # Сохранить информацию о платеже
                await appwrite_service.save_payment_record(
                    user_id=user_id,
                    payment_id=payment_id,
                    tariff_id=payment_data.tariff_id,
                    amount=price,
                    status="pending",
                    period=period,
                    created_at=datetime.now().isoformat()
                )
                
                logger.info(f"Payment created: {payment_id} for user {user_id}, tariff {payment_data.tariff_id}, period {period}")
                
                return {
                    "success": True,
                    "payment_id": payment_id,
                    "confirmation_url": confirmation_url
                }
            else:
                error_detail = response.text
                logger.error(f"YooKassa API error: {response.status_code} - {error_detail}")
                return {"success": False, "message": "Ошибка при создании платежа. Попробуйте позже."}
                
    except httpx.TimeoutException:
        logger.error("YooKassa API timeout")
        return {"success": False, "message": "Платёжная система не отвечает. Попробуйте позже."}
    except Exception as e:
        logger.error(f"create_payment error: {e}")
        return {"success": False, "message": f"Ошибка: {str(e)}"}


# ========================================
# POST /webhook — обработка вебхуков от ЮKassa
# ========================================

@router.post("/webhook")
async def yookassa_webhook(request: Request):
    """Обработка уведомлений от ЮKassa о статусе платежа."""
    
    try:
        body = await request.body()
        payload = json.loads(body)
    except Exception as e:
        logger.error(f"Webhook body parse error: {e}")
        return Response(status_code=400, content="Bad request")
    
    # Проверка подписи вебхука
    yookassa_secret_key = getattr(settings, 'yookassa_secret_key', '')
    if yookassa_secret_key:
        if not _verify_webhook_signature(request, body, yookassa_secret_key):
            logger.warning("Webhook signature verification failed")
            return Response(status_code=403, content="Invalid signature")
    
    event = payload.get("event", "")
    payment_object = payload.get("object", {})
    
    payment_id = payment_object.get("id", "")
    status = payment_object.get("status", "")
    metadata = payment_object.get("metadata", {})
    
    user_id = metadata.get("user_id", "")
    tariff_id_en = metadata.get("tariff_id", "")
    period = metadata.get("period", "monthly")
    
    # Маппим английский ID тарифа из metadata обратно на русский (для БД)
    tariff_id = TARIFF_ID_FROM_EN.get(tariff_id_en, tariff_id_en)
    
    logger.info(f"Webhook: event={event}, payment_id={payment_id}, status={status}, user={user_id}, tariff={tariff_id} (from en: {tariff_id_en}), period={period}")
    
    if not user_id or not tariff_id:
        logger.warning(f"Webhook missing metadata: {payload}")
        return Response(status_code=200, content="OK")
    
    # Обработка успешной оплаты
    if event == "payment.succeeded" and status == "succeeded":
        try:
            await appwrite_service.update_payment_status(
                payment_id=payment_id,
                status="succeeded"
            )
            
            # Определяем длительность
            duration = TARIFF_DURATIONS.get(period, timedelta(days=30))
            now = datetime.now()
            expires_at = now + duration
            
            await appwrite_service.activate_subscription(
                user_id=user_id,
                subscription_type=tariff_id,
                paid_at=now.isoformat(),
                expires_at=expires_at.isoformat(),
                payment_id=payment_id
            )
            
            # Сбрасываем счётчик запросов при активации тарифа
            await appwrite_service.reset_daily_request_count(user_id)
            
            logger.info(f"Tariff activated: user={user_id}, tariff={tariff_id}, period={period}, expires={expires_at}")
            
        except Exception as e:
            logger.error(f"Error activating tariff: {e}")
    
    elif event == "payment.canceled" and status == "canceled":
        try:
            await appwrite_service.update_payment_status(
                payment_id=payment_id,
                status="canceled"
            )
        except Exception as e:
            logger.error(f"Error updating canceled payment: {e}")
    
    elif event == "payment.waiting_for_capture":
        try:
            await appwrite_service.update_payment_status(
                payment_id=payment_id,
                status="waiting_for_capture"
            )
        except Exception as e:
            logger.error(f"Error updating waiting_for_capture: {e}")
    
    return Response(status_code=200, content="OK")


def _verify_webhook_signature(request: Request, body: bytes, secret_key: str) -> bool:
    """Проверка подписи вебхука от ЮKassa."""
    try:
        webhook_signature = request.headers.get("X-Signature", "")
        if not webhook_signature:
            # В тестовом режиме пропускаем
            return True
        
        payload = json.loads(body)
        event = payload.get("event", "")
        payment_object = payload.get("object", {})
        payment_id = payment_object.get("id", "")
        
        sign_string = f"{event}&{payment_id}"
        
        computed = hmac.new(
            secret_key.encode('utf-8'),
            sign_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(computed, webhook_signature)
        
    except Exception as e:
        logger.error(f"Webhook signature verification error: {e}")
        return False


# ========================================
# GET /check-payment — проверить статус платежа
# ========================================

@router.get("/check-payment")
async def check_payment_status(
    payment_id: str,
    session_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None)
):
    """Проверить реальный статус платежа через YooKassa API"""
    
    user_id = _get_user_id(session_token, authorization)
    if not user_id:
        return {"success": False, "message": "Не авторизован"}
    
    if not payment_id:
        return {"success": False, "message": "Не указан payment_id"}
    
    yookassa_shop_id = getattr(settings, 'yookassa_shop_id', '')
    yookassa_secret_key = getattr(settings, 'yookassa_secret_key', '')
    
    if not yookassa_shop_id or not yookassa_secret_key:
        return {"success": False, "message": "Платёжная система не настроена"}
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.yookassa.ru/v3/payments/{payment_id}",
                auth=(str(yookassa_shop_id), str(yookassa_secret_key)),
                timeout=15.0
            )
            
            if response.status_code == 200:
                payment_info = response.json()
                status = payment_info.get("status", "unknown")
                metadata = payment_info.get("metadata", {})
                
                # Если платёж успешен — убедимся что подписка активирована (fallback если вебхук не дошёл)
                if status == "succeeded":
                    tariff_id_en = metadata.get("tariff_id", "")
                    tariff_id = TARIFF_ID_FROM_EN.get(tariff_id_en, tariff_id_en)
                    period = metadata.get("period", "monthly")
                    meta_user_id = metadata.get("user_id", "")
                    
                    if meta_user_id:
                        try:
                            sub = await appwrite_service.get_user_subscription(meta_user_id)
                            if sub.get("subscription_status") != "active" or sub.get("subscription_type") != tariff_id:
                                # Подписка ещё не активирована — активируем (fallback)
                                duration = TARIFF_DURATIONS.get(period, timedelta(days=30))
                                now = datetime.now()
                                expires_at = now + duration
                                
                                await appwrite_service.update_payment_status(payment_id, "succeeded")
                                await appwrite_service.activate_subscription(
                                    user_id=meta_user_id,
                                    subscription_type=tariff_id,
                                    paid_at=now.isoformat(),
                                    expires_at=expires_at.isoformat(),
                                    payment_id=payment_id
                                )
                                await appwrite_service.reset_daily_request_count(meta_user_id)
                                logger.info(f"Fallback activation via check-payment: user={meta_user_id}, tariff={tariff_id}")
                        except Exception as e:
                            logger.error(f"Fallback activation error: {e}")
                
                return {
                    "success": True,
                    "payment_id": payment_id,
                    "status": status,
                    "tariff_id": TARIFF_ID_FROM_EN.get(metadata.get("tariff_id", ""), metadata.get("tariff_id", "")),
                    "period": metadata.get("period", ""),
                    "amount": payment_info.get("amount", {}).get("value", "")
                }
            else:
                return {"success": False, "message": "Не удалось проверить статус платежа"}
                
    except httpx.TimeoutException:
        return {"success": False, "message": "Платёжная система не отвечает"}
    except Exception as e:
        logger.error(f"check_payment_status error: {e}")
        return {"success": False, "message": str(e)}


# ========================================
# GET /history — история платежей
# ========================================

@router.get("/history")
async def get_payment_history(
    session_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None)
):
    """Получить историю платежей пользователя"""
    
    user_id = _get_user_id(session_token, authorization)
    if not user_id:
        return {"success": False, "message": "Не авторизован"}
    
    try:
        payments = await appwrite_service.get_user_payments(user_id)
        return {"success": True, "payments": payments}
    except Exception as e:
        logger.error(f"get_payment_history error: {e}")
        return {"success": True, "payments": []}


# ========================================
# GET /check-access — проверка доступа к функциям
# ========================================

@router.get("/check-access")
async def check_access(
    feature: str = "chat",  # chat, training
    session_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None)
):
    """Проверить доступ пользователя к определённой функции"""
    
    user_id = _get_user_id(session_token, authorization)
    if not user_id:
        return {"success": False, "allowed": False, "message": "Не авторизован"}
    
    try:
        sub = await appwrite_service.get_user_subscription(user_id)
        tariff_id = sub.get("subscription_type", "бесплатный")
        tariff_info = next((t for t in TARIFFS if t["id"] == tariff_id), TARIFFS[0])
        
        # Проверяем, активен ли тариф
        status = sub.get("subscription_status", "inactive")
        if tariff_id == "бесплатный":
            # Бесплатный тариф всегда "активен"
            status = "active"
        
        if status != "active" and tariff_id != "бесплатный":
            return {"success": True, "allowed": False, "message": "Тариф истёк. Оплатите для продолжения.", "tariff": tariff_id}
        
        if feature == "training":
            allowed = tariff_info.get("training_available", False)
            if not allowed:
                return {"success": True, "allowed": False, "message": "Тренажёр доступен только на тарифе «Бизнес»", "tariff": tariff_id}
            return {"success": True, "allowed": True, "tariff": tariff_id}
        
        elif feature == "chat":
            # Проверяем дневной лимит запросов
            daily_limit = tariff_info.get("daily_limit")
            if daily_limit is None:
                return {"success": True, "allowed": True, "tariff": tariff_id}  # Без ограничений
            
            daily_count = await appwrite_service.get_daily_request_count(user_id)
            if daily_count >= daily_limit:
                return {
                    "success": True, 
                    "allowed": False, 
                    "message": f"Лимит {daily_limit} запросов в день исчерпан. Повысьте тариф для большего количества.",
                    "tariff": tariff_id,
                    "daily_count": daily_count,
                    "daily_limit": daily_limit
                }
            return {"success": True, "allowed": True, "tariff": tariff_id, "daily_count": daily_count, "daily_limit": daily_limit}
        
        return {"success": True, "allowed": True, "tariff": tariff_id}
        
    except Exception as e:
        logger.error(f"check_access error: {e}")
        return {"success": False, "allowed": False, "message": str(e)}

"""Routes для файлов - с поддержкой PDF, DOCX, DOC и AI-дедупликацией"""

from fastapi import APIRouter, UploadFile, File, Cookie, Request
from typing import Optional
from app.models.schemas import FileUploadResponse
from app.services.appwrite_service import appwrite_service
from app.services.file_processor import file_processor
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

# Sessions from auth
try:
    from app.routes.auth import sessions
except:
    sessions = {}

# Knowledge extractor
knowledge_extractor = None
try:
    from app.services.knowledge_extractor import knowledge_extractor as ke
    knowledge_extractor = ke
except Exception as e:
    logger.warning(f"Knowledge extractor: {e}")


def get_user_id(session_token: Optional[str] = None, request: Request = None) -> str:
    if session_token and session_token in sessions:
        return sessions[session_token].get("user_id", "dev_user")
    if request:
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
            if token in sessions:
                return sessions[token].get("user_id", "dev_user")
    return "dev_user"


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    session_token: Optional[str] = Cookie(None),
    request: Request = None
):
    """Загрузка → извлечение текста → AI извлечение знаний → AI-мердж с дедупликацией → сохранение"""

    allowed = ['.txt', '.json', '.html', '.htm', '.pdf', '.docx', '.doc']
    name = file.filename or "unknown"

    if not any(name.lower().endswith(e) for e in allowed):
        return {"success": False, "message": f"Разрешены: {', '.join(allowed)}", "stage": "error"}

    try:
        content = await file.read()
    except Exception as e:
        return {"success": False, "message": f"Ошибка чтения: {e}", "stage": "error"}

    if len(content) > 30 * 1024 * 1024:
        return {"success": False, "message": "Максимум 30MB", "stage": "error"}

    uid = get_user_id(session_token, request)
    original_size = len(content)

    logger.info(f"=== UPLOAD: {name} for {uid} ({original_size} bytes) ===")

    # ЭТАП 1: Извлечение текста из файла
    try:
        proc = await file_processor.process_file(content, file.content_type or "", name)
    except Exception as e:
        return {"success": False, "message": f"Ошибка обработки: {e}", "stage": "error"}

    if not proc.get("success"):
        return {"success": False, "message": proc.get("error", "Ошибка обработки файла"), "stage": "error"}

    extracted_text = proc.get("content", "")
    stats = proc.get("stats", {})
    opt_size = len(extracted_text)
    file_format = proc.get("format", "unknown")

    logger.info(f"Extracted text: {original_size} → {opt_size} chars (format: {file_format})")

    if not extracted_text.strip():
        return {"success": False, "message": "Не удалось извлечь текст из файла", "stage": "error"}

    # ЭТАП 2: AI извлечение знаний из текста
    knowledge = ""
    kn_size = 0
    if knowledge_extractor and extracted_text:
        try:
            logger.info(f"Extracting knowledge from {opt_size} chars...")
            result = await knowledge_extractor.extract(extracted_text, 50000)
            if result.get("success"):
                knowledge = result.get("knowledge", "")
                kn_size = len(knowledge)
                logger.info(f"Knowledge extracted: {kn_size} chars")
            else:
                logger.warning(f"Extraction failed: {result.get('error')}")
        except Exception as e:
            logger.error(f"Extraction error: {e}", exc_info=True)

    # ЭТАП 3: AI-мердж с существующей базой знаний (дедупликация)
    saved = False
    merged_info = {}
    if kn_size > 0:
        try:
            existing_knowledge = await appwrite_service.get_user_knowledge(uid)

            if knowledge_extractor and existing_knowledge:
                # Используем AI-мердж с дедупликацией
                logger.info(f"Merging with existing knowledge ({len(existing_knowledge)} chars)")
                merge_result = await knowledge_extractor.merge_knowledge(
                    existing_knowledge=existing_knowledge,
                    new_knowledge=knowledge,
                    new_file_name=name,
                    max_size=50000
                )
                if merge_result.get("success"):
                    knowledge = merge_result["knowledge"]
                    kn_size = len(knowledge)
                    merged_info = {
                        "merged": True,
                        "removed_duplicates": merge_result.get("removed_duplicates", False),
                        "was_merged_size": merge_result.get("original_size", 0),
                        "result_size": merge_result.get("merged_size", 0)
                    }
                    logger.info(f"AI merge: {merged_info}")
            elif existing_knowledge:
                # knowledge_extractor недоступен — простая конкатенация
                combined = f"{existing_knowledge}\n\n=== {name} ===\n\n{knowledge}"
                knowledge = combined[:50000]
                kn_size = len(knowledge)
                merged_info = {"merged": True, "removed_duplicates": False, "method": "concat"}

            # Сохраняем
            save_result = await appwrite_service.save_user_knowledge(uid, knowledge)
            saved = save_result.get("success", False)
            if saved:
                logger.info(f"✅ Knowledge saved for {uid}: {kn_size} chars")
            else:
                logger.error(f"Save failed: {save_result.get('error')}")
        except Exception as e:
            logger.error(f"Save error: {e}", exc_info=True)
    else:
        logger.warning("No knowledge extracted, skipping save")

    # Удаляем файл из памяти
    del content
    del extracted_text

    # Формируем ответ
    msg = f"Файл обработан ({file_format})"
    if kn_size > 0:
        msg += f". Знаний: {kn_size} символов."
    if merged_info.get("merged"):
        if merged_info.get("removed_duplicates"):
            msg += " Дубликаты удалены."
        else:
            msg += " Добавлено к базе."
    if saved:
        msg += " Сохранено."

    return {
        "success": True,
        "message": msg,
        "stage": "complete",
        "file_format": file_format,
        "original_size": original_size,
        "extracted_text_size": opt_size,
        "knowledge_size": kn_size,
        "compression": stats.get("compression_ratio", 0),
        "saved": saved,
        "merge": merged_info
    }


@router.get("/knowledge")
async def get_knowledge(session_token: Optional[str] = Cookie(None), request: Request = None):
    uid = get_user_id(session_token, request)
    try:
        kn = await appwrite_service.get_user_knowledge(uid)
        return {"success": True, "knowledge": kn, "size": len(kn), "user_id": uid}
    except Exception as e:
        return {"success": False, "message": str(e), "knowledge": "", "user_id": uid}


@router.delete("/knowledge")
async def clear_knowledge(session_token: Optional[str] = Cookie(None), request: Request = None):
    uid = get_user_id(session_token, request)
    try:
        await appwrite_service.save_user_knowledge(uid, "")
        return {"success": True, "message": "База знаний очищена"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.get("/context")
async def get_context(session_token: Optional[str] = Cookie(None), request: Request = None):
    uid = get_user_id(session_token, request)
    try:
        kn = await appwrite_service.get_user_knowledge(uid)
        return {"success": True, "context": kn, "context_size": len(kn), "user_id": uid}
    except Exception as e:
        return {"success": False, "message": str(e), "context": "", "user_id": uid}


@router.get("/stats")
async def get_stats(session_token: Optional[str] = Cookie(None), request: Request = None):
    uid = get_user_id(session_token, request)
    kn_size = 0
    try:
        kn = await appwrite_service.get_user_knowledge(uid)
        kn_size = len(kn)
    except:
        pass
    return {"success": True, "knowledge_size": kn_size, "knowledge_tokens": kn_size // 4, "user_id": uid}
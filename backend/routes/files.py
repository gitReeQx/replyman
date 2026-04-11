"""Routes для файлов - с поддержкой PDF, DOCX, DOC, AI-дедупликацией и фоновой обработкой"""

from fastapi import APIRouter, UploadFile, File, Cookie, Request
from typing import Optional, Dict
from app.models.schemas import FileUploadResponse
from app.services.appwrite_service import appwrite_service
from app.services.file_processor import file_processor
import logging
import asyncio
import uuid
import time

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

# ========================================
# Хранилище задач фоновой обработки
# ========================================

_upload_tasks: Dict[str, dict] = {}

# Автоочистка старых задач (старше 30 минут)
_cleanup_interval = 300  # секунд


async def _cleanup_old_tasks():
    """Периодически удаляет завершённые задачи старше 30 минут"""
    while True:
        await asyncio.sleep(_cleanup_interval)
        now = time.time()
        expired = [
            tid for tid, task in _upload_tasks.items()
            if task.get("status") in ("complete", "error") and now - task.get("completed_at", 0) > 1800
        ]
        for tid in expired:
            del _upload_tasks[tid]
        if expired:
            logger.info(f"Cleaned up {len(expired)} old upload tasks")


# Запускаем фоновую очистку при импорте
asyncio.create_task(_cleanup_old_tasks())


def get_user_id(session_token: Optional[str] = None, request: Request = None) -> Optional[str]:
    if session_token and session_token in sessions:
        return sessions[session_token].get("user_id")
    if request:
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
            if token in sessions:
                return sessions[token].get("user_id")
    return None


def _update_task(task_id: str, **kwargs):
    """Обновляет статус задачи"""
    if task_id in _upload_tasks:
        _upload_tasks[task_id].update(kwargs)


# ========================================
# Фоновая обработка файла
# ========================================

async def _process_file_background(task_id: str, content: bytes, filename: str, content_type: str, uid: str):
    """Полный пайплайн обработки файла в фоне с обновлением статуса на каждом этапе"""

    try:
        original_size = len(content)

        # --- ЭТАП 1: Извлечение текста ---
        _update_task(task_id, status="processing", stage="extracting", stage_label="Извлечение текста",
                     stage_detail=f"Чтение файла {filename}...", progress=10)

        try:
            proc = await file_processor.process_file(content, content_type, filename)
        except Exception as e:
            _update_task(task_id, status="error", stage="error",
                         message=f"Ошибка обработки: {e}", completed_at=time.time())
            return

        if not proc.get("success"):
            _update_task(task_id, status="error", stage="error",
                         message=proc.get("error", "Ошибка обработки файла"), completed_at=time.time())
            return

        extracted_text = proc.get("content", "")
        stats = proc.get("stats", {})
        opt_size = len(extracted_text)
        file_format = proc.get("format", "unknown")

        logger.info(f"[{task_id}] Extracted text: {original_size} → {opt_size} chars (format: {file_format})")

        if not extracted_text.strip():
            _update_task(task_id, status="error", stage="error",
                         message="Не удалось извлечь текст из файла", completed_at=time.time())
            return

        _update_task(task_id, stage="extracted", stage_label="Текст извлечён",
                     stage_detail=f"{original_size} → {opt_size} символов", progress=25)

        # --- ЭТАП 2: AI извлечение знаний ---
        knowledge = ""
        kn_size = 0

        if knowledge_extractor and extracted_text:
            try:
                _update_task(task_id, stage="ai_extract", stage_label="ИИ анализирует текст",
                             stage_detail="Извлечение ключевых знаний...", progress=40)

                result = await knowledge_extractor.extract(extracted_text, 100000)

                if result.get("success"):
                    knowledge = result.get("knowledge", "")
                    kn_size = len(knowledge)
                    logger.info(f"[{task_id}] Knowledge extracted: {kn_size} chars")
                    _update_task(task_id, stage="ai_extracted", stage_label="Знания извлечены",
                                 stage_detail=f"{kn_size} символов знаний", progress=60)
                else:
                    logger.warning(f"[{task_id}] Extraction failed: {result.get('error')}")
                    _update_task(task_id, stage="ai_extracted", stage_label="Знания не извлечены",
                                 stage_detail="Переходим к сохранению", progress=60)
            except Exception as e:
                logger.error(f"[{task_id}] Extraction error: {e}", exc_info=True)
                _update_task(task_id, stage="ai_extracted", stage_label="Ошибка извлечения знаний",
                             stage_detail=str(e), progress=60)

        # --- ЭТАП 3: AI-мердж с существующей базой знаний ---
        saved = False
        merged_info = {}

        if kn_size > 0:
            try:
                _update_task(task_id, stage="merging", stage_label="Слияние с базой знаний",
                             stage_detail="Удаление дубликатов...", progress=70)

                existing_knowledge = await appwrite_service.get_user_knowledge(uid)

                if knowledge_extractor and existing_knowledge:
                    logger.info(f"[{task_id}] Merging with existing knowledge ({len(existing_knowledge)} chars)")
                    _update_task(task_id, stage_detail="ИИ объединяет знания и удаляет дубликаты...", progress=75)

                    merge_result = await knowledge_extractor.merge_knowledge(
                        existing_knowledge=existing_knowledge,
                        new_knowledge=knowledge,
                        new_file_name=filename,
                        max_size=100000
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
                        logger.info(f"[{task_id}] AI merge: {merged_info}")
                elif existing_knowledge:
                    combined = f"{existing_knowledge}\n\n=== {filename} ===\n\n{knowledge}"
                    knowledge = combined[:100000]
                    kn_size = len(knowledge)
                    merged_info = {"merged": True, "removed_duplicates": False, "method": "concat"}

                # --- ЭТАП 4: Сохранение ---
                _update_task(task_id, stage="saving", stage_label="Сохранение",
                             stage_detail="Запись в базу данных...", progress=85)

                save_result = await appwrite_service.save_user_knowledge(uid, knowledge)
                saved = save_result.get("success", False)

                if saved:
                    logger.info(f"[{task_id}] ✅ Knowledge saved for {uid}: {kn_size} chars")
                else:
                    logger.error(f"[{task_id}] Save failed: {save_result.get('error')}")
            except Exception as e:
                logger.error(f"[{task_id}] Save error: {e}", exc_info=True)
        else:
            logger.warning(f"[{task_id}] No knowledge extracted, skipping save")

        # --- Финал: метаданные ---
        _update_task(task_id, stage="finalizing", stage_label="Финализация",
                     stage_detail="Обновление статистики...", progress=92)

        del content
        del extracted_text

        # Сохраняем имя файла в список
        try:
            await appwrite_service.add_user_file_name(uid, filename)
        except Exception as e:
            logger.warning(f"[{task_id}] Failed to save file name: {e}")

        # Инкрементируем счётчик
        try:
            await appwrite_service.increment_user_stat(uid, "files_count")
        except Exception as e:
            logger.warning(f"[{task_id}] Failed to increment files_count: {e}")

        # Получаем обновлённый список файлов
        file_names = []
        try:
            file_names = await appwrite_service.get_user_file_names(uid)
        except:
            pass

        # Формируем итоговое сообщение
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

        result_data = {
            "success": True,
            "message": msg,
            "file_name": filename,
            "file_format": file_format,
            "original_size": original_size,
            "extracted_text_size": opt_size,
            "knowledge_size": kn_size,
            "compression": stats.get("compression_ratio", 0),
            "saved": saved,
            "merge": merged_info,
            "file_names": file_names
        }

        _update_task(task_id, status="complete", stage="complete", stage_label="Готово!",
                     stage_detail=msg, progress=100, result=result_data, completed_at=time.time())
        logger.info(f"[{task_id}] ✅ Upload task completed successfully")

    except Exception as e:
        logger.error(f"[{task_id}] Fatal error in background processing: {e}", exc_info=True)
        _update_task(task_id, status="error", stage="error",
                     message=f"Критическая ошибка: {e}", completed_at=time.time())


# ========================================
# REST endpoints
# ========================================

@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    session_token: Optional[str] = Cookie(None),
    request: Request = None
):
    """Быстро принимает файл, запускает обработку в фоне, возвращает task_id"""

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
    if not uid:
        return {"success": False, "message": "Не авторизован", "stage": "error"}
    content_type = file.content_type or ""

    # Создаём задачу
    task_id = str(uuid.uuid4())[:12]
    _upload_tasks[task_id] = {
        "status": "processing",
        "stage": "uploading",
        "stage_label": "Файл получен",
        "stage_detail": f"{name} ({len(content)} байт)",
        "progress": 5,
        "file_name": name,
        "user_id": uid,
        "created_at": time.time(),
        "result": None
    }

    logger.info(f"=== UPLOAD START: {name} → task {task_id} for {uid} ({len(content)} bytes) ===")

    # Запускаем обработку в фоне
    asyncio.create_task(
        _process_file_background(task_id, content, name, content_type, uid)
    )

    return {
        "success": True,
        "task_id": task_id,
        "message": "Файл принят, обработка начата"
    }


@router.get("/upload/status/{task_id}")
async def get_upload_status(task_id: str):
    """Возвращает текущий статус фоновой задачи обработки файла"""
    task = _upload_tasks.get(task_id)

    if not task:
        return {"success": False, "message": "Задача не найдена", "status": "not_found"}

    response = {
        "success": True,
        "task_id": task_id,
        "status": task.get("status", "unknown"),
        "stage": task.get("stage", ""),
        "stage_label": task.get("stage_label", ""),
        "stage_detail": task.get("stage_detail", ""),
        "progress": task.get("progress", 0),
        "file_name": task.get("file_name", "")
    }

    # Если задача завершена — возвращаем полный результат
    if task.get("status") == "complete" and task.get("result"):
        response["result"] = task["result"]
    elif task.get("status") == "error":
        response["message"] = task.get("message", "Неизвестная ошибка")

    return response


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
        # Также очищаем список файлов и сбрасываем счётчик
        try:
            await appwrite_service.clear_user_file_names(uid)
        except:
            pass
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

    # Получаем счётчик загруженных файлов из Appwrite
    files_count = 0
    try:
        stats = await appwrite_service.get_user_stats(uid)
        files_count = stats.get("files_count", 0)
    except:
        pass

    # Получаем список имён файлов
    file_names = []
    try:
        file_names = await appwrite_service.get_user_file_names(uid)
    except:
        pass

    return {"success": True, "knowledge_size": kn_size, "knowledge_tokens": kn_size // 4, "user_id": uid, "files_count": files_count, "file_names": file_names}

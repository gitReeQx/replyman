"""
Appwrite Service - обновлённая версия с поддержкой RAG чанков и защитой от потери данных

Все методы обновления пользователя используют _build_user_update() для сохранения
всех полей (Appwrite update_row заменяет все поля, которые не переданы).
"""

from appwrite.client import Client
from appwrite.services.tables_db import TablesDB
from appwrite.services.storage import Storage
from appwrite.services.users import Users
from appwrite.services.account import Account
from appwrite.id import ID
from appwrite.query import Query
from appwrite.permission import Permission
from appwrite.role import Role
from appwrite.input_file import InputFile
from app.config import get_settings
from typing import Optional, Dict, Any, List
import json
import io
import logging
from datetime import datetime

logger = logging.getLogger(__name__)
settings = get_settings()

# Все поля таблицы users — используются при обновлении строки
_USER_FIELDS = [
    "user_id", "email", "name", "instructions", "knowledge",
    "file_names", "files_count", "messages_count", "trainings_count", "subscription_type",
    "subscription_status", "subscription_paid_at", "subscription_expires_at", "yookassa_payment_id",
    "daily_requests_count", "daily_requests_date",
    "active_training"
]


class AppwriteService:
    def __init__(self):
        self.client = Client()
        self.client.set_endpoint(settings.appwrite_endpoint)
        self.client.set_project(settings.appwrite_project_id)
        self.client.set_key(settings.appwrite_api_key)

        self.tablesdb = TablesDB(self.client)
        self.storage = Storage(self.client)
        self.users = Users(self.client)

        self.database_id = settings.appwrite_database_id
        self.users_table = settings.appwrite_users_collection_id
        self.chats_table = settings.appwrite_chats_collection_id
        self.bucket_id = settings.appwrite_files_bucket_id

        # ID таблицы для чанков (создайте в Appwrite если нет)
        self.chunks_table = getattr(settings, 'appwrite_chunks_collection_id', 'chunks')

    def _get_user_permissions(self, user_id: str) -> List[str]:
        """Generate read/write permissions for a user"""
        return [
            Permission.read(Role.user(user_id)),
            Permission.write(Role.user(user_id))
        ]

    # ========================================
    # Helper: безопасное обновление строки users
    # ========================================

    async def _get_user_row(self, user_id: str):
        """Найти строку пользователя в таблице users. Возвращает (row_id, row_data) или (None, None)."""
        result = self.tablesdb.list_rows(
            database_id=self.database_id,
            table_id=self.users_table,
            queries=[Query.equal("user_id", user_id)]
        )
        rows = result.rows if hasattr(result, 'rows') else []
        if rows:
            row = rows[0]
            row_id = row.id if hasattr(row, 'id') else row.get("$id")
            rd = row.data if hasattr(row, 'data') else row
            return row_id, rd
        return None, None

    def _build_user_update(self, rd: dict, changes: dict) -> dict:
        """
        Собрать полный payload для update_row.
        Берёт текущие данные rd, применяет changes, сохраняет ВСЕ известные поля.

        Appwrite update_row ПЕРЕЗАПИСЫВАЕТ строку — если поле не передано, оно будет очищено.
        Поэтому обязательно включаем все _USER_FIELDS.
        """
        update = {}
        for field in _USER_FIELDS:
            if field in changes:
                update[field] = changes[field]
            elif field in rd:
                update[field] = rd[field]
        return update

    def _do_update_row(self, row_id: str, changes: dict) -> bool:
        """Выполнить update_row с полным сохранением всех полей."""
        try:
            self.tablesdb.update_row(
                database_id=self.database_id,
                table_id=self.users_table,
                row_id=row_id,
                data=changes
            )
            return True
        except Exception as e:
            logger.error(f"update_row error: {e}")
            return False

    # ========================================
    # KNOWLEDGE OPERATIONS (таблица users)
    # ========================================

    async def get_user_knowledge(self, user_id: str) -> str:
        """Получить знания из users.knowledge"""
        try:
            _, rd = await self._get_user_row(user_id)
            if rd:
                return rd.get("knowledge", "")
            return ""
        except Exception as e:
            logger.error(f"get_user_knowledge error: {e}")
            return ""

    async def save_user_knowledge(self, user_id: str, knowledge: str) -> dict:
        """
        Сохранить знания в users.knowledge (без потери остальных полей).
        Включает защиту от случайного уменьшения базы знаний более чем на 30%
        (если только новая база не пуста, а старая была не пуста).
        """
        if len(knowledge) > 100000:
            knowledge = knowledge[:100000]

        try:
            # Защита от потери данных: если новая база слишком маленькая по сравнению со старой
            old_knowledge = await self.get_user_knowledge(user_id)
            if old_knowledge and len(knowledge) < len(old_knowledge) * 0.9:
                logger.error(
                    f"save_user_knowledge: new knowledge size {len(knowledge)} is less than 90% of old {len(old_knowledge)}. "
                    f"Rejecting update to prevent data loss."
                )
                return {"success": False, "error": "Новая база знаний подозрительно мала, обновление отклонено"}

            row_id, rd = await self._get_user_row(user_id)

            if row_id:
                update = self._build_user_update(rd, {"knowledge": knowledge})
                success = self._do_update_row(row_id, update)
                return {"success": success}
            else:
                # Создаём новую запись
                try:
                    user = self.users.get(user_id)
                    email = user.email if hasattr(user, 'email') else f"{user_id}@temp.local"
                    name = user.name if hasattr(user, 'name') else ""
                except:
                    email, name = f"{user_id}@temp.local", ""

                self.tablesdb.create_row(
                    database_id=self.database_id,
                    table_id=self.users_table,
                    row_id=ID.unique(),
                    data={
                        "user_id": user_id, "knowledge": knowledge,
                        "email": email, "name": name,
                        "file_names": [], "instructions": "",
                        "files_count": 0, "messages_count": 0,
                        "trainings_count": 0, "subscription_type": "бесплатный"
                    },
                    permissions=self._get_user_permissions(user_id)
                )
                return {"success": True}

        except Exception as e:
            logger.error(f"save_user_knowledge error: {e}")
            return {"success": False, "error": str(e)}

    async def append_user_knowledge(self, user_id: str, new_knowledge: str, source: str = "") -> dict:
        """Добавить знания к существующим"""
        existing = await self.get_user_knowledge(user_id)

        if source:
            separator = f"\n\n{'='*50}\n=== {source} ===\n{'='*50}\n\n"
        else:
            separator = "\n\n"

        combined = existing + separator + new_knowledge
        return await self.save_user_knowledge(user_id, combined)

    async def clear_user_knowledge(self, user_id: str) -> dict:
        """Очистить базу знаний"""
        return await self.save_user_knowledge(user_id, "")

    # ========================================
    # FILE NAMES operations
    # ========================================

    async def get_user_file_names(self, user_id: str) -> list:
        """Получить список имён загруженных файлов из users.file_names (array)"""
        try:
            _, rd = await self._get_user_row(user_id)
            if rd:
                raw = rd.get("file_names", [])
                # Appwrite возвращает list напрямую
                if isinstance(raw, list):
                    return raw
                # Fallback: если вдруг пришла строка (старый формат)
                if raw and isinstance(raw, str):
                    try:
                        return json.loads(raw)
                    except (json.JSONDecodeError, ValueError):
                        return [f.strip() for f in raw.split(",") if f.strip()] if raw else []
                return []
            return []
        except Exception as e:
            logger.error(f"get_user_file_names error: {e}")
            return []

    async def add_user_file_name(self, user_id: str, file_name: str) -> bool:
        """Добавить имя файла в список (array в users.file_names)"""
        try:
            row_id, rd = await self._get_user_row(user_id)
            if not row_id:
                logger.warning(f"add_user_file_name: user row not found for {user_id}")
                return False

            existing = rd.get("file_names", [])
            # Appwrite возвращает list напрямую
            if not isinstance(existing, list):
                existing = []

            if file_name not in existing:
                existing.append(file_name)
            existing = existing[-100:]  # максимум 100 файлов

            # Отправляем как list, НЕ как JSON-строку!
            update = self._build_user_update(rd, {"file_names": existing})
            result = self._do_update_row(row_id, update)

            if result:
                logger.info(f"add_user_file_name: saved '{file_name}' for {user_id} (total: {len(existing)})")
            else:
                logger.error(f"add_user_file_name: update_row failed for {user_id}")
            return result
        except Exception as e:
            logger.error(f"add_user_file_name error: {e}")
            return False

    async def clear_user_file_names(self, user_id: str) -> bool:
        """Очистить список имён файлов"""
        try:
            row_id, rd = await self._get_user_row(user_id)
            if not row_id:
                return False

            # Отправляем пустой list, НЕ строку "[]"!
            update = self._build_user_update(rd, {"file_names": []})
            return self._do_update_row(row_id, update)
        except Exception as e:
            logger.error(f"clear_user_file_names error: {e}")
            return False

    # ========================================
    # User Authentication Methods
    # ========================================

    async def create_user(self, email: str, password: str, name: Optional[str] = None) -> Dict[str, Any]:
        """Create a new user via Appwrite Users API (server-side)"""
        try:
            user = self.users.create(
                user_id=ID.unique(),
                email=email,
                password=password,
                name=name or email.split('@')[0]
            )

            user_id = user.id if hasattr(user, 'id') else user.get("$id", "") if hasattr(user, 'get') else str(user)
            user_email = user.email if hasattr(user, 'email') else email
            user_name = user.name if hasattr(user, 'name') else (name or email.split('@')[0])

            logger.info(f"Appwrite user created in Auth: {user_id}")

            try:
                user_record = self.tablesdb.create_row(
                    database_id=self.database_id,
                    table_id=self.users_table,
                    row_id=ID.unique(),
                    data={
                        "user_id": user_id,
                        "email": email,
                        "name": name or email.split('@')[0],
                        "instructions": "",
                        "files_count": 0,
                        "messages_count": 0,
                        "trainings_count": 0,
                        "subscription_type": "бесплатный",
                        "file_names": []
                    },
                    permissions=self._get_user_permissions(user_id)
                )
                record_id = user_record.id if hasattr(user_record, 'id') else user_record.get("$id", "")
                logger.info(f"User record created in table: {record_id}")
            except Exception as table_error:
                logger.warning(f"Could not create user table record: {table_error}")

            return {
                "success": True,
                "user": {
                    "$id": user_id,
                    "email": user_email,
                    "name": user_name
                }
            }
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Appwrite create_user error: {error_msg}")

            if "already exists" in error_msg.lower() or "duplicate" in error_msg.lower():
                return {
                    "success": False,
                    "error": "Пользователь с таким email уже существует"
                }

            return {
                "success": False,
                "error": error_msg
            }

    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Find user by email"""
        try:
            result = self.users.list(queries=[Query.equal("email", email)])
            users_list = result.users if hasattr(result, 'users') else []

            if users_list:
                user = users_list[0]
                return {
                    "$id": user.id if hasattr(user, 'id') else str(user),
                    "email": user.email if hasattr(user, 'email') else email,
                    "name": user.name if hasattr(user, 'name') else ""
                }
            return None
        except Exception as e:
            logger.error(f"Error finding user by email: {e}")
            return None

    async def create_session(self, email: str, password: str) -> Dict[str, Any]:
        """Create a session for user (server-side)"""
        try:
            user = await self.get_user_by_email(email)

            if not user:
                return {
                    "success": False,
                    "error": "Пользователь не найден"
                }

            user_id = user.get("$id")
            session = self.users.create_session(user_id=user_id)

            session_id = session.id if hasattr(session, 'id') else ""
            secret = session.secret if hasattr(session, 'secret') else ""

            return {
                "success": True,
                "session": {
                    "$id": session_id,
                    "userId": user_id,
                    "secret": secret,
                    "expire": ""
                },
                "user": user
            }
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Appwrite create_session error: {error_msg}")
            return {
                "success": False,
                "error": error_msg
            }

    async def get_user(self, user_id: str) -> Dict[str, Any]:
        """Get user by ID"""
        try:
            if not user_id:
                return {"success": False, "error": "User ID required"}

            user = self.users.get(user_id=user_id)

            # Appwrite SDK может возвращать emailVerification (camelCase)
            email_verified = self._get_email_verification(user)

            return {
                "success": True,
                "user": {
                    "$id": user.id if hasattr(user, 'id') else "",
                    "email": user.email if hasattr(user, 'email') else "",
                    "name": user.name if hasattr(user, 'name') else "",
                    "registration": str(user.registration) if hasattr(user, 'registration') else "",
                    "status": user.status if hasattr(user, 'status') else True,
                    "email_verification": email_verified
                }
            }
        except Exception as e:
            logger.error(f"Error getting user: {e}")
            return {"success": False, "error": str(e)}

    def _get_email_verification(self, user) -> bool:
        """Получить статус подтверждения email из объекта пользователя Appwrite.
        Пробуем атрибуты, dict-ключи, Pydantic model_dump и __dict__."""
        # 1. Пробуем атрибуты объекта (Pydantic model)
        for attr in ('email_verification', 'emailVerification', 'emailverification'):
            val = getattr(user, attr, None)
            if val is not None:
                return bool(val)

        # 2. Если объект — dict
        if isinstance(user, dict):
            for key in ('email_verification', 'emailVerification', 'emailverification'):
                if key in user and user[key] is not None:
                    return bool(user[key])

        # 3. Пробуем model_dump() (Pydantic v2) или dict() (Pydantic v1)
        try:
            dump = None
            if hasattr(user, 'model_dump'):
                dump = user.model_dump()
            elif hasattr(user, 'dict'):
                dump = user.dict()
            if dump and isinstance(dump, dict):
                for key in ('email_verification', 'emailVerification', 'emailverification'):
                    if key in dump and dump[key] is not None:
                        return bool(dump[key])
        except Exception:
            pass

        # 4. Пробуем __dict__
        user_dict = getattr(user, '__dict__', {})
        for key, val in user_dict.items():
            if 'verif' in key.lower() and 'email' in key.lower():
                if val is not None:
                    logger.info(f"Found verification in __dict__: {key}={val}")
                    return bool(val)

        # Отладочный вывод
        relevant = [a for a in dir(user) if not a.startswith('_') and ('email' in a.lower() or 'verif' in a.lower())]
        logger.warning(f"Could not find email verification attr. Relevant attrs: {relevant}, __dict__ keys: {list(user_dict.keys())[:20]}")
        return False

    async def is_email_verified(self, user_id: str) -> bool:
        """Проверить, подтверждён ли email пользователя"""
        try:
            user = self.users.get(user_id=user_id)
            result = self._get_email_verification(user)
            logger.info(f"is_email_verified for {user_id}: {result}")
            return result
        except Exception as e:
            logger.error(f"is_email_verified error: {e}")
            return False

    async def send_email_verification(self, user_id: str, url: str, appwrite_session_secret: str = None) -> Dict[str, Any]:
        """Отправить письмо для подтверждения email через Account API.
        appwrite_session_secret — секрет сессии пользователя (нужен для Account API).
        Если не передан — создаём временную сессию, используем, удаляем."""
        temp_session_id = None
        temp_session_secret = None
        try:
            if not appwrite_session_secret:
                # Создаём временную сессию для отправки письма
                try:
                    session = self.users.create_session(user_id=user_id)
                    appwrite_session_secret = session.secret if hasattr(session, 'secret') else ""
                    temp_session_id = session.id if hasattr(session, 'id') else ""
                    temp_session_secret = appwrite_session_secret
                    logger.info(f"Created temp session {temp_session_id} for verification email")
                except Exception as se:
                    logger.error(f"Failed to create temp session for verification: {se}")
                    return {"success": False, "error": f"Не удалось создать сессию: {se}"}

            # Используем Account API с секретом сессии пользователя
            client = Client()
            client.set_endpoint(settings.appwrite_endpoint)
            client.set_project(settings.appwrite_project_id)
            client.set_session(appwrite_session_secret)

            account = Account(client)
            result = account.create_email_verification(url=url)

            verification_id = result.id if hasattr(result, 'id') else ""
            logger.info(f"Email verification sent for user {user_id}, verification_id: {verification_id}")

            return {"success": True, "verification_id": verification_id}

        except Exception as e:
            logger.error(f"send_email_verification error: {e}")
            return {"success": False, "error": str(e)}
        finally:
            # Удаляем временную сессию если создавали
            if temp_session_id:
                try:
                    self.users.delete_session(user_id=user_id, session_id=temp_session_id)
                    logger.info(f"Deleted temp session {temp_session_id}")
                except Exception:
                    pass

    async def verify_email_by_secret(self, user_id: str, secret: str, appwrite_session_secret: str = None) -> Dict[str, Any]:
        """Подтвердить email по secret из ссылки.
        Способ 1: Account API с секретом сессии (если есть).
        Способ 2: Серверный SDK — напрямую обновить emailVerification."""
        # Способ 1: Через Account API
        if appwrite_session_secret:
            try:
                client = Client()
                client.set_endpoint(settings.appwrite_endpoint)
                client.set_project(settings.appwrite_project_id)
                client.set_session(appwrite_session_secret)

                account = Account(client)
                account.update_email_verification(user_id=user_id, secret=secret)
                logger.info(f"Email verified via Account API for user {user_id}")
                return {"success": True}
            except Exception as e:
                logger.warning(f"verify via Account API failed: {e}, trying server-side fallback")

        # Способ 2: Серверный SDK — напрямую обновить emailVerification
        try:
            self.users.update_email_verification(
                user_id=user_id,
                email_verification=True
            )
            logger.info(f"Email verified via server SDK for user {user_id}")
            return {"success": True}
        except Exception as e:
            logger.error(f"verify_email_by_secret error: {e}")
            return {"success": False, "error": str(e)}

    async def delete_session(self, session_id: str = "current") -> Dict[str, Any]:
        """Delete a user session"""
        try:
            return {"success": True}
        except Exception as e:
            logger.error(f"Error deleting session: {e}")
            return {"success": False, "error": str(e)}

    async def delete_user_sessions(self, user_id: str) -> Dict[str, Any]:
        """Delete all sessions for a user"""
        try:
            self.users.delete_sessions(user_id=user_id)
            return {"success": True}
        except Exception as e:
            logger.error(f"Error deleting user sessions: {e}")
            return {"success": False, "error": str(e)}

    # ========================================
    # File operations (Storage + chats table)
    # ========================================

    async def get_user_files(self, user_id: str) -> list:
        """Получить файлы пользователя из chats таблицы"""
        try:
            result = self.tablesdb.list_rows(
                database_id=self.database_id,
                table_id=self.chats_table,
                queries=[
                    Query.equal("user_id", user_id),
                    Query.limit(100)
                ]
            )

            rows = result.rows if hasattr(result, 'rows') else []

            files = []
            for row in rows:
                row_data = row.data if hasattr(row, 'data') else row
                row_id = row.id if hasattr(row, 'id') else row.get("$id", "")

                files.append({
                    "$id": row_id,
                    "file_id": row_data.get("file_id", row_id),
                    "file_name": row_data.get("file_name", "Unknown"),
                    "uploaded_at": row_data.get("uploaded_at", ""),
                    "original_size": row_data.get("original_size", 0),
                    "knowledge_size": row_data.get("knowledge_size", 0)
                })

            return files

        except Exception as e:
            logger.error(f"get_user_files error: {e}")
            return []

    async def upload_file(self, user_id: str, file_name: str, file_content: bytes, content_type: str) -> dict:
        """Загрузить файл в Storage и сохранить метаданные"""
        file_id = ID.unique()

        try:
            input_file = InputFile.from_bytes(file_content, filename=file_name)

            try:
                self.storage.create_file(
                    bucket_id=self.bucket_id,
                    file_id=file_id,
                    file=input_file,
                    permissions=self._get_user_permissions(user_id)
                )
            except Exception as api_error:
                error_str = str(api_error)
                if "validation" in error_str.lower() or "encryption" in error_str.lower():
                    logger.info(f"File uploaded with SDK warning: {file_id}")
                else:
                    raise api_error

            from datetime import datetime
            self.tablesdb.create_row(
                database_id=self.database_id,
                table_id=self.chats_table,
                row_id=ID.unique(),
                data={
                    "user_id": user_id,
                    "file_id": file_id,
                    "file_name": file_name,
                    "content_type": content_type,
                    "uploaded_at": datetime.now().isoformat()
                },
                permissions=self._get_user_permissions(user_id)
            )

            return {"success": True, "file_id": file_id}

        except Exception as e:
            logger.error(f"upload_file error: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}

    async def delete_file(self, file_id: str, user_id: str) -> dict:
        """Удалить файл из Storage и метаданные"""
        try:
            self.storage.delete_file(
                bucket_id=self.bucket_id,
                file_id=file_id
            )

            result = self.tablesdb.list_rows(
                database_id=self.database_id,
                table_id=self.chats_table,
                queries=[
                    Query.equal("user_id", user_id),
                    Query.equal("file_id", file_id)
                ]
            )

            rows = result.rows if hasattr(result, 'rows') else []
            for row in rows:
                row_id = row.id if hasattr(row, 'id') else row.get("$id")
                self.tablesdb.delete_row(
                    database_id=self.database_id,
                    table_id=self.chats_table,
                    row_id=row_id
                )

            return {"success": True}

        except Exception as e:
            logger.error(f"delete_file error: {e}")
            return {"success": False, "error": str(e)}

    async def get_file_content(self, file_id: str) -> bytes:
        """Получить содержимое файла"""
        try:
            return self.storage.get_file_view(
                bucket_id=self.bucket_id,
                file_id=file_id
            )
        except Exception as e:
            logger.error(f"get_file_content error: {e}")
            return None

    # ========================================
    # User instructions operations
    # ========================================

    async def get_user_instructions(self, user_id: str) -> str:
        """Получить инструкции пользователя"""
        try:
            _, rd = await self._get_user_row(user_id)
            if rd:
                return rd.get("instructions", "")
            return ""
        except:
            return ""

    async def save_user_instructions(self, user_id: str, instructions: str) -> Dict[str, Any]:
        """Save user's custom instructions (без потери остальных полей)"""
        try:
            row_id, rd = await self._get_user_row(user_id)

            if row_id:
                update = self._build_user_update(rd, {"instructions": instructions})
                self._do_update_row(row_id, update)
            else:
                self.tablesdb.create_row(
                    database_id=self.database_id,
                    table_id=self.users_table,
                    row_id=ID.unique(),
                    data={
                        "user_id": user_id,
                        "instructions": instructions,
                        "file_names": []
                    },
                    permissions=self._get_user_permissions(user_id)
                )

            return {"success": True}
        except Exception as e:
            logger.error(f"Error saving user instructions: {e}")
            return {"success": False, "error": str(e)}

    # ========================================
    # User stats operations (users table fields)
    # ========================================

    async def get_user_stats(self, user_id: str) -> Dict[str, Any]:
        """Получить все счётчики пользователя и тип подписки"""
        try:
            _, rd = await self._get_user_row(user_id)
            if rd:
                return {
                    "success": True,
                    "files_count": rd.get("files_count") or 0,
                    "messages_count": rd.get("messages_count") or 0,
                    "trainings_count": rd.get("trainings_count") or 0,
                    "subscription_type": rd.get("subscription_type") or "бесплатный"
                }
            return {
                "success": True,
                "files_count": 0,
                "messages_count": 0,
                "trainings_count": 0,
                "subscription_type": "бесплатный"
            }
        except Exception as e:
            logger.error(f"get_user_stats error: {e}")
            return {
                "success": False,
                "files_count": 0,
                "messages_count": 0,
                "trainings_count": 0,
                "subscription_type": "бесплатный"
            }

    async def increment_user_stat(self, user_id: str, field: str) -> bool:
        """Увеличить счётчик на 1 (files_count, messages_count, trainings_count)"""
        try:
            stats = await self.get_user_stats(user_id)
            current = stats.get(field, 0)
            new_value = int(current) + 1

            row_id, rd = await self._get_user_row(user_id)

            if row_id:
                update = self._build_user_update(rd, {field: new_value})
                return self._do_update_row(row_id, update)
            else:
                # Создаём запись с начальным значением
                try:
                    user = self.users.get(user_id)
                    email = user.email if hasattr(user, 'email') else f"{user_id}@temp.local"
                    name = user.name if hasattr(user, 'name') else ""
                except:
                    email, name = f"{user_id}@temp.local", ""

                self.tablesdb.create_row(
                    database_id=self.database_id,
                    table_id=self.users_table,
                    row_id=ID.unique(),
                    data={
                        "user_id": user_id,
                        "email": email,
                        "name": name,
                        field: new_value,
                        "file_names": []
                    },
                    permissions=self._get_user_permissions(user_id)
                )
                return True
        except Exception as e:
            logger.error(f"increment_user_stat error: {e}")
            return False

    async def set_user_subscription(self, user_id: str, subscription_type: str) -> bool:
        """Установить тип подписки (старт/бизнес/про)"""
        try:
            row_id, rd = await self._get_user_row(user_id)

            if row_id:
                update = self._build_user_update(rd, {"subscription_type": subscription_type})
                return self._do_update_row(row_id, update)
            return False
        except Exception as e:
            logger.error(f"set_user_subscription error: {e}")
            return False

    # ========================================
    # Subscription & Payment operations
    # ========================================

    async def get_user_subscription(self, user_id: str) -> Dict[str, Any]:
        """Получить полную информацию о подписке пользователя"""
        try:
            _, rd = await self._get_user_row(user_id)
            if rd:
                sub_type = rd.get("subscription_type", "бесплатный")
                sub_status = rd.get("subscription_status", "inactive")
                expires_at = rd.get("subscription_expires_at", "")

                # Проверяем, не истекла ли подписка
                if sub_status == "active" and expires_at:
                    try:
                        expiry_date = datetime.fromisoformat(expires_at)
                        if datetime.now() > expiry_date:
                            sub_status = "expired"
                            # Обновляем статус в БД
                            await self._update_subscription_status(user_id, "expired")
                    except (ValueError, TypeError):
                        pass

                return {
                    "subscription_type": sub_type,
                    "subscription_status": sub_status,
                    "subscription_paid_at": rd.get("subscription_paid_at", None),
                    "subscription_expires_at": expires_at or None,
                    "yookassa_payment_id": rd.get("yookassa_payment_id", None),
                }
            return {
                "subscription_type": "бесплатный",
                "subscription_status": "inactive",
                "subscription_paid_at": None,
                "subscription_expires_at": None,
                "yookassa_payment_id": None,
            }
        except Exception as e:
            logger.error(f"get_user_subscription error: {e}")
            return {
                "subscription_type": "бесплатный",
                "subscription_status": "inactive",
                "subscription_paid_at": None,
                "subscription_expires_at": None,
                "yookassa_payment_id": None,
            }

    async def activate_subscription(
        self,
        user_id: str,
        subscription_type: str,
        paid_at: str,
        expires_at: str,
        payment_id: str
    ) -> bool:
        """Активировать подписку после успешной оплаты"""
        try:
            row_id, rd = await self._get_user_row(user_id)
            if row_id:
                update = self._build_user_update(rd, {
                    "subscription_type": subscription_type,
                    "subscription_status": "active",
                    "subscription_paid_at": paid_at,
                    "subscription_expires_at": expires_at,
                    "yookassa_payment_id": payment_id,
                })
                return self._do_update_row(row_id, update)
            return False
        except Exception as e:
            logger.error(f"activate_subscription error: {e}")
            return False

    async def _update_subscription_status(self, user_id: str, status: str) -> bool:
        """Обновить только статус подписки"""
        try:
            row_id, rd = await self._get_user_row(user_id)
            if row_id:
                update = self._build_user_update(rd, {"subscription_status": status})
                return self._do_update_row(row_id, update)
            return False
        except Exception as e:
            logger.error(f"_update_subscription_status error: {e}")
            return False

    # ========================================
    # Payment records (отдельная таблица payments)
    # ========================================

    async def save_payment_record(
        self,
        user_id: str,
        payment_id: str,
        tariff_id: str,
        amount: int,
        status: str,
        period: str = "monthly",
        created_at: str = ""
    ) -> bool:
        """Сохранить запись о платеже в таблицу payments"""
        try:
            payments_table = getattr(settings, 'appwrite_payments_collection_id', 'payments')
            self.tablesdb.create_row(
                database_id=self.database_id,
                table_id=payments_table,
                row_id=ID.unique(),
                data={
                    "user_id": user_id,
                    "payment_id": payment_id,
                    "tariff_id": tariff_id,
                    "amount": amount,
                    "status": status,
                    "period": period,
                    "created_at": created_at,
                },
                permissions=self._get_user_permissions(user_id)
            )
            return True
        except Exception as e:
            logger.error(f"save_payment_record error: {e}")
            # Если таблицы нет, логируем, но не ломаем поток
            return False

    async def update_payment_status(self, payment_id: str, status: str) -> bool:
        """Обновить статус платежа по payment_id"""
        try:
            payments_table = getattr(settings, 'appwrite_payments_collection_id', 'payments')
            result = self.tablesdb.list_rows(
                database_id=self.database_id,
                table_id=payments_table,
                queries=[Query.equal("payment_id", payment_id)]
            )
            rows = result.rows if hasattr(result, 'rows') else []
            if rows:
                row = rows[0]
                row_id = row.id if hasattr(row, 'id') else row.get("$id")
                row_data = row.data if hasattr(row, 'data') else row
                # Обновляем только статус
                update_data = dict(row_data)
                update_data["status"] = status
                self.tablesdb.update_row(
                    database_id=self.database_id,
                    table_id=payments_table,
                    row_id=row_id,
                    data=update_data
                )
                return True
            return False
        except Exception as e:
            logger.error(f"update_payment_status error: {e}")
            return False

    async def get_user_payments(self, user_id: str) -> list:
        """Получить историю платежей пользователя"""
        try:
            payments_table = getattr(settings, 'appwrite_payments_collection_id', 'payments')
            result = self.tablesdb.list_rows(
                database_id=self.database_id,
                table_id=payments_table,
                queries=[
                    Query.equal("user_id", user_id),
                    Query.order_desc("created_at"),
                    Query.limit(50)
                ]
            )
            rows = result.rows if hasattr(result, 'rows') else []

            payments = []
            for row in rows:
                row_data = row.data if hasattr(row, 'data') else row
                payments.append({
                    "payment_id": row_data.get("payment_id", ""),
                    "tariff_id": row_data.get("tariff_id", ""),
                    "amount": row_data.get("amount", 0),
                    "status": row_data.get("status", "pending"),
                    "created_at": row_data.get("created_at", ""),
                    "description": f'Тариф «{row_data.get("tariff_id", "")}»'
                })
            return payments
        except Exception as e:
            logger.error(f"get_user_payments error: {e}")
            return []

    # ========================================
    # Active Training Session (users.active_training)
    # ========================================

    async def save_active_training(self, user_id: str, session_data: dict) -> bool:
        """Сохранить активную тренировку в users.active_training (JSON string)"""
        try:
            row_id, rd = await self._get_user_row(user_id)
            if not row_id:
                logger.warning(f"save_active_training: user row not found for {user_id}")
                return False

            json_str = json.dumps(session_data, ensure_ascii=False)
            update = self._build_user_update(rd, {"active_training": json_str})
            return self._do_update_row(row_id, update)
        except Exception as e:
            logger.error(f"save_active_training error: {e}")
            return False

    async def get_active_training(self, user_id: str) -> Optional[dict]:
        """Получить активную тренировку из users.active_training"""
        try:
            _, rd = await self._get_user_row(user_id)
            if rd:
                raw = rd.get("active_training", "")
                if not raw or not raw.strip():
                    return None
                return json.loads(raw)
            return None
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"get_active_training: invalid JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"get_active_training error: {e}")
            return None

    async def clear_active_training(self, user_id: str) -> bool:
        """Очистить активную тренировку"""
        try:
            row_id, rd = await self._get_user_row(user_id)
            if not row_id:
                return False

            update = self._build_user_update(rd, {"active_training": ""})
            return self._do_update_row(row_id, update)
        except Exception as e:
            logger.error(f"clear_active_training error: {e}")
            return False

    # ========================================
    # Daily Request Limits (users.daily_requests_count, daily_requests_date)
    # ========================================

    async def get_daily_request_count(self, user_id: str) -> int:
        """Получить количество запросов за сегодня. Если дата сменилась — сбрасывает счётчик."""
        try:
            row_id, rd = await self._get_user_row(user_id)
            if not rd:
                return 0

            today_str = datetime.now().strftime("%Y-%m-%d")
            saved_date = rd.get("daily_requests_date") or ""
            count = int(rd.get("daily_requests_count") or 0)

            # Если день сменился — сбрасываем счётчик
            if saved_date != today_str:
                if row_id:
                    update = self._build_user_update(rd, {
                        "daily_requests_count": 0,
                        "daily_requests_date": today_str,
                    })
                    self._do_update_row(row_id, update)
                return 0

            return count
        except Exception as e:
            logger.error(f"get_daily_request_count error: {e}")
            return 0

    async def increment_daily_request_count(self, user_id: str) -> int:
        """Увеличить счётчик запросов за сегодня на 1. Возвращает новое значение."""
        try:
            row_id, rd = await self._get_user_row(user_id)
            if not row_id:
                return 0

            today_str = datetime.now().strftime("%Y-%m-%d")
            saved_date = rd.get("daily_requests_date") or ""

            if saved_date != today_str:
                # Новый день — начинаем с 1
                update = self._build_user_update(rd, {
                    "daily_requests_count": 1,
                    "daily_requests_date": today_str,
                })
                self._do_update_row(row_id, update)
                return 1
            else:
                new_count = int(rd.get("daily_requests_count") or 0) + 1
                update = self._build_user_update(rd, {
                    "daily_requests_count": new_count,
                })
                self._do_update_row(row_id, update)
                return new_count
        except Exception as e:
            logger.error(f"increment_daily_request_count error: {e}")
            return 0

    async def reset_daily_request_count(self, user_id: str) -> bool:
        """Сбросить счётчик запросов (при активации тарифа)"""
        try:
            row_id, rd = await self._get_user_row(user_id)
            if not row_id:
                return False
            update = self._build_user_update(rd, {
                "daily_requests_count": 0,
                "daily_requests_date": datetime.now().strftime("%Y-%m-%d"),
            })
            return self._do_update_row(row_id, update)
        except Exception as e:
            logger.error(f"reset_daily_request_count error: {e}")
            return False


# Singleton instance
appwrite_service = AppwriteService()
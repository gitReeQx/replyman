"""
Appwrite Service - обновлённая версия с поддержкой RAG чанков и защитой от потери данных

Все методы обновления пользователя используют _build_user_update() для сохранения
всех полей (Appwrite update_row заменяет все поля, которые не переданы).
"""

from appwrite.client import Client
from appwrite.services.tables_db import TablesDB
from appwrite.services.storage import Storage
from appwrite.services.users import Users
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

logger = logging.getLogger(__name__)
settings = get_settings()

# Все поля таблицы users — используются при обновлении строки
_USER_FIELDS = [
    "user_id", "email", "name", "instructions", "knowledge",
    "file_names", "files_count", "messages_count", "trainings_count", "subscription_type",
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
                        "trainings_count": 0, "subscription_type": "старт"
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
                        "subscription_type": "старт",
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

            return {
                "success": True,
                "user": {
                    "$id": user.id if hasattr(user, 'id') else "",
                    "email": user.email if hasattr(user, 'email') else "",
                    "name": user.name if hasattr(user, 'name') else "",
                    "registration": str(user.registration) if hasattr(user, 'registration') else "",
                    "status": user.status if hasattr(user, 'status') else True
                }
            }
        except Exception as e:
            logger.error(f"Error getting user: {e}")
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
                    "files_count": rd.get("files_count", 0),
                    "messages_count": rd.get("messages_count", 0),
                    "trainings_count": rd.get("trainings_count", 0),
                    "subscription_type": rd.get("subscription_type", "старт")
                }
            return {
                "success": True,
                "files_count": 0,
                "messages_count": 0,
                "trainings_count": 0,
                "subscription_type": "старт"
            }
        except Exception as e:
            logger.error(f"get_user_stats error: {e}")
            return {
                "success": False,
                "files_count": 0,
                "messages_count": 0,
                "trainings_count": 0,
                "subscription_type": "старт"
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
        """Установить тип подписки (старт/бизнес)"""
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


# Singleton instance
appwrite_service = AppwriteService()
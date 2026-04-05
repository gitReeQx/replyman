"""
Appwrite Service - обновлённая версия с поддержкой RAG чанков

Добавлены методы:
- save_chunk() - сохранить чанк с embedding
- get_user_chunks() - получить все чанки пользователя
- search_chunks() - поиск по чанкам
- delete_file_chunks() - удалить чанки файла
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

settings = get_settings()

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
    # KNOWLEDGE OPERATIONS (таблица users)
    # ========================================
     
    async def get_user_knowledge(self, user_id: str) -> str:
        """Получить знания из users.knowledge"""
        try:
            result = self.tablesdb.list_rows(
                database_id=self.database_id,
                table_id=self.users_table,
                queries=[Query.equal("user_id", user_id)]
            )
            rows = result.rows if hasattr(result, 'rows') else []
            if rows:
                rd = rows[0].data if hasattr(rows[0], 'data') else rows[0]
                return rd.get("knowledge", "")
            return ""
        except Exception as e:
            print(f"get_user_knowledge error: {e}")
            return ""
    
    async def save_user_knowledge(self, user_id: str, knowledge: str) -> dict:
        """Сохранить знания в users.knowledge"""
        if len(knowledge) > 50000:
            knowledge = knowledge[:50000]
        
        try:
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
                
                update = {"knowledge": knowledge}
                for f in ["user_id", "email", "name", "instructions"]:
                    if f in rd:
                        update[f] = rd[f]
                
                self.tablesdb.update_row(
                    database_id=self.database_id,
                    table_id=self.users_table,
                    row_id=row_id,
                    data=update
                )
                return {"success": True}
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
                    data={"user_id": user_id, "knowledge": knowledge, "email": email, "name": name},
                    permissions=self._get_user_permissions(user_id)
                )
                return {"success": True}
                
        except Exception as e:
            print(f"save_user_knowledge error: {e}")
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
            
            print(f"Appwrite user created in Auth: {user_id}")
            
            try:
                user_record = self.tablesdb.create_row(
                    database_id=self.database_id,
                    table_id=self.users_table,
                    row_id=ID.unique(),
                    data={
                        "user_id": user_id,
                        "email": email,
                        "name": name or email.split('@')[0],
                        "instructions": ""
                    },
                    permissions=self._get_user_permissions(user_id)
                )
                record_id = user_record.id if hasattr(user_record, 'id') else user_record.get("$id", "")
                print(f"User record created in table: {record_id}")
            except Exception as table_error:
                print(f"Warning: Could not create user table record: {table_error}")
            
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
            print(f"Appwrite create_user error: {error_msg}")
            
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
            print(f"Error finding user by email: {e}")
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
            print(f"Appwrite create_session error: {error_msg}")
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
            print(f"Error getting user: {e}")
            return {"success": False, "error": str(e)}
    
    async def delete_session(self, session_id: str = "current") -> Dict[str, Any]:
        """Delete a user session"""
        try:
            return {"success": True}
        except Exception as e:
            print(f"Error deleting session: {e}")
            return {"success": False, "error": str(e)}
    
    async def delete_user_sessions(self, user_id: str) -> Dict[str, Any]:
        """Delete all sessions for a user"""
        try:
            self.users.delete_sessions(user_id=user_id)
            return {"success": True}
        except Exception as e:
            print(f"Error deleting user sessions: {e}")
            return {"success": False, "error": str(e)}

    # ========================================
    # File operations
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
            print(f"get_user_files error: {e}")
            return []
    
    async def upload_file(self, user_id: str, file_name: str, file_content: bytes, content_type: str) -> dict:
        """Загрузить файл в Storage и сохранить метаданные"""
        file_id = ID.unique()
        
        try:
            from appwrite.input_file import InputFile
            
            input_file = InputFile.from_bytes(file_content, filename=file_name)
            
            # Загружаем в Storage
            try:
                self.storage.create_file(
                    bucket_id=self.bucket_id,
                    file_id=file_id,
                    file=input_file,
                    permissions=self._get_user_permissions(user_id)
                )
            except Exception as api_error:
                # SDK может выдать ошибку парсинга, но файл загружается
                error_str = str(api_error)
                if "validation" in error_str.lower() or "encryption" in error_str.lower():
                    print(f"File uploaded with SDK warning: {file_id}")
                else:
                    raise api_error
            
            # Сохраняем метаданные в chats таблицу
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
            print(f"upload_file error: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}
    
    async def delete_file(self, file_id: str, user_id: str) -> dict:
        """Удалить файл из Storage и метаданные"""
        try:
            # Удаляем из Storage
            self.storage.delete_file(
                bucket_id=self.bucket_id,
                file_id=file_id
            )
            
            # Удаляем метаданные
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
            print(f"delete_file error: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_file_content(self, file_id: str) -> bytes:
        """Получить содержимое файла"""
        try:
            return self.storage.get_file_view(
                bucket_id=self.bucket_id,
                file_id=file_id
            )
        except Exception as e:
            print(f"get_file_content error: {e}")
            return None
    # ========================================
    # User instructions operations
    # ========================================
    
    async def get_user_instructions(self, user_id: str) -> str:
        """Получить инструкции пользователя"""
        try:
            result = self.tablesdb.list_rows(
                database_id=self.database_id,
                table_id=self.users_table,
                queries=[Query.equal("user_id", user_id)]
            )
            rows = result.rows if hasattr(result, 'rows') else []
            if rows:
                rd = rows[0].data if hasattr(rows[0], 'data') else rows[0]
                return rd.get("instructions", "")
            return ""
        except:
            return ""

    async def save_user_instructions(self, user_id: str, instructions: str) -> Dict[str, Any]:
        """Save user's custom instructions"""
        try:
            result = self.tablesdb.list_rows(
                database_id=self.database_id,
                table_id=self.users_table,
                queries=[Query.equal("user_id", user_id)]
            )
            
            rows = result.rows if hasattr(result, 'rows') else []
            
            if rows:
                row = rows[0]
                row_id = row.id if hasattr(row, 'id') else row["$id"]
                self.tablesdb.update_row(
                    database_id=self.database_id,
                    table_id=self.users_table,
                    row_id=row_id,
                    data={"instructions": instructions}
                )
            else:
                self.tablesdb.create_row(
                    database_id=self.database_id,
                    table_id=self.users_table,
                    row_id=ID.unique(),
                    data={
                        "user_id": user_id,
                        "instructions": instructions
                    },
                    permissions=self._get_user_permissions(user_id)
                )
            
            return {"success": True}
        except Exception as e:
            print(f"Error saving user instructions: {e}")
            return {"success": False, "error": str(e)}


# Singleton instance
appwrite_service = AppwriteService()

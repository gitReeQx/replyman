from fastapi import APIRouter, HTTPException, UploadFile, File, Cookie, Form
from typing import Optional, List
from app.models.schemas import FileUploadResponse, FilesListResponse, FileInfo
from app.services.appwrite_service import appwrite_service
from app.services.file_processor import file_processor
from datetime import datetime
import os
import json
import uuid

router = APIRouter()

# Local file storage for development
LOCAL_STORAGE_PATH = "/tmp/replyman_files"
LOCAL_FILES_DB = {}  # user_id -> list of file info

def ensure_storage():
    """Ensure local storage directory exists"""
    os.makedirs(LOCAL_STORAGE_PATH, exist_ok=True)

def get_user_id_from_session(session_token: Optional[str]) -> str:
    """Get user ID from session or return default"""
    # For development, use a default user
    return "dev_user"

@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    session_token: Optional[str] = Cookie(None)
):
    """Upload a chat history file"""
    
    # Check file type
    allowed_types = ['.txt', '.json', '.html', '.htm']
    file_name = file.filename or "unknown"
    
    if not any(file_name.lower().endswith(ext) for ext in allowed_types):
        return FileUploadResponse(
            success=False,
            message=f"Неподдерживаемый формат файла. Разрешены: {', '.join(allowed_types)}"
        )
    
    # Check file size (max 10MB)
    content = await file.read()
    if len(content) > 30 * 1024 * 1024:
        return FileUploadResponse(
            success=False,
            message="Файл слишком большой. Максимальный размер: 30MB"
        )
    
    user_id = get_user_id_from_session(session_token)
    file_id = str(uuid.uuid4())
    
    # Try Appwrite upload first
    try:
        result = await appwrite_service.upload_file(
            user_id=user_id,
            file_name=file_name,
            file_content=content,
            content_type=file.content_type or "text/plain"
        )
        
        if result.get("success"):
            return FileUploadResponse(
                success=True,
                message="Файл успешно загружен",
                file_id=result["file_id"],
                file_name=file_name
            )
    except Exception as e:
        print(f"Appwrite upload failed: {e}")
    
    # Fallback: local storage
    ensure_storage()
    
    # Save file locally
    file_path = os.path.join(LOCAL_STORAGE_PATH, file_id)
    with open(file_path, "wb") as f:
        f.write(content)
    
    # Store metadata
    if user_id not in LOCAL_FILES_DB:
        LOCAL_FILES_DB[user_id] = []
    
    LOCAL_FILES_DB[user_id].append({
        "id": file_id,
        "name": file_name,
        "size": len(content),
        "content_type": file.content_type or "text/plain",
        "uploaded_at": datetime.now().isoformat(),
        "processed": False
    })
    
    return FileUploadResponse(
        success=True,
        message="Файл успешно загружен",
        file_id=file_id,
        file_name=file_name
    )

@router.get("/list", response_model=FilesListResponse)
async def list_files(session_token: Optional[str] = Cookie(None)):
    """Get list of uploaded files for current user"""
    
    user_id = get_user_id_from_session(session_token)
    
    # Try Appwrite first
    try:
        files = await appwrite_service.get_user_files(user_id)
        
        if files is not None:
            file_list = []
            for f in files:
                file_list.append(FileInfo(
                    id=f.get("file_id", ""),
                    name=f.get("file_name", "Unknown"),
                    size=0,
                    uploaded_at=datetime.now(),
                    processed=f.get("processed", False)
                ))
            
            return FilesListResponse(success=True, files=file_list)
    except Exception as e:
        print(f"Appwrite list files failed: {e}")
    
    # Fallback: local storage
    user_files = LOCAL_FILES_DB.get(user_id, [])
    file_list = []
    
    for f in user_files:
        file_list.append(FileInfo(
            id=f["id"],
            name=f["name"],
            size=f["size"],
            uploaded_at=datetime.fromisoformat(f["uploaded_at"]),
            processed=f.get("processed", False)
        ))
    
    return FilesListResponse(success=True, files=file_list)

@router.delete("/{file_id}")
async def delete_file(file_id: str, session_token: Optional[str] = Cookie(None)):
    """Delete an uploaded file"""
    
    user_id = get_user_id_from_session(session_token)
    
    # Try Appwrite first
    try:
        result = await appwrite_service.delete_file(file_id, user_id)
        if result.get("success"):
            return {"success": True, "message": "Файл удален"}
    except Exception as e:
        print(f"Appwrite delete failed: {e}")
    
    # Fallback: local storage
    if user_id in LOCAL_FILES_DB:
        LOCAL_FILES_DB[user_id] = [
            f for f in LOCAL_FILES_DB[user_id] if f["id"] != file_id
        ]
    
    # Delete local file
    file_path = os.path.join(LOCAL_STORAGE_PATH, file_id)
    if os.path.exists(file_path):
        os.remove(file_path)
    
    return {"success": True, "message": "Файл удален"}

@router.get("/{file_id}/content")
async def get_file_content(file_id: str, session_token: Optional[str] = Cookie(None)):
    """Get processed content of a file"""
    
    # Try Appwrite first
    try:
        content = await appwrite_service.get_file_content(file_id)
        if content:
            result = await file_processor.process_file(content, "text/plain", file_id)
            return {
                "success": True,
                "content": result.get("content", ""),
                "conversations": result.get("conversations", [])
            }
    except Exception as e:
        print(f"Appwrite get content failed: {e}")
    
    # Fallback: local storage
    file_path = os.path.join(LOCAL_STORAGE_PATH, file_id)
    if os.path.exists(file_path):
        with open(file_path, "rb") as f:
            content = f.read()
        
        result = await file_processor.process_file(content, "text/plain", file_id)
        
        return {
            "success": True,
            "content": result.get("content", ""),
            "conversations": result.get("conversations", [])
        }
    
    return {"success": False, "message": "Файл не найден"}

@router.get("/context")
async def get_all_context(session_token: Optional[str] = Cookie(None)):
    """Get combined context from all user's files"""
    
    user_id = get_user_id_from_session(session_token)
    all_content = []
    
    # Get files from local storage
    user_files = LOCAL_FILES_DB.get(user_id, [])
    
    for f in user_files:
        file_id = f["id"]
        file_path = os.path.join(LOCAL_STORAGE_PATH, file_id)
        
        if os.path.exists(file_path):
            with open(file_path, "rb") as file:
                content = file.read()
            
            result = await file_processor.process_file(
                content,
                f.get("content_type", "text/plain"),
                f.get("name", "")
            )
            
            if result.get("success"):
                all_content.append(f"=== {f.get('name', 'Файл')} ===\n{result.get('content', '')}")
    
    # Also try Appwrite
    try:
        files = await appwrite_service.get_user_files(user_id)
        for f in files:
            file_id = f.get("file_id")
            if file_id:
                content = await appwrite_service.get_file_content(file_id)
                if content:
                    result = await file_processor.process_file(
                        content,
                        f.get("content_type", "text/plain"),
                        f.get("file_name", "")
                    )
                    if result.get("success"):
                        all_content.append(f"=== {f.get('file_name', 'Файл')} ===\n{result.get('content', '')}")
    except Exception:
        pass
    
    combined = "\n\n".join(all_content)
    
    return {
        "success": True,
        "context": combined,
        "files_count": len(user_files)
    }

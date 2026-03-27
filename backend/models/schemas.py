from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime

# Auth models
class UserRegister(BaseModel):
    email: EmailStr
    password: str
    name: Optional[str] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: str
    email: str
    name: Optional[str] = None
    created_at: Optional[datetime] = None

class AuthResponse(BaseModel):
    success: bool
    message: str
    user: Optional[UserResponse] = None
    session_token: Optional[str] = None

# Chat models
class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str
    timestamp: Optional[datetime] = None

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    use_context: bool = True

class ChatResponse(BaseModel):
    success: bool
    message: str
    response: Optional[str] = None
    session_id: Optional[str] = None

# File models
class FileUploadResponse(BaseModel):
    success: bool
    message: str
    file_id: Optional[str] = None
    file_name: Optional[str] = None

class FileInfo(BaseModel):
    id: str
    name: str
    size: int
    uploaded_at: datetime
    processed: bool

class FilesListResponse(BaseModel):
    success: bool
    files: List[FileInfo]

# Training models
class TrainingStartRequest(BaseModel):
    scenario: Optional[str] = "general"  # general, sales, support, etc.

class TrainingMessage(BaseModel):
    message: str
    session_id: str

class TrainingResponse(BaseModel):
    success: bool
    message: str
    response: Optional[str] = None
    role: Optional[str] = None  # "client" or "feedback"
    session_id: Optional[str] = None

class TrainingEndRequest(BaseModel):
    session_id: str

class TrainingFeedback(BaseModel):
    success: bool
    overall_score: Optional[float] = None
    strengths: Optional[List[str]] = None
    weaknesses: Optional[List[str]] = None
    recommendations: Optional[List[str]] = None
    full_feedback: Optional[str] = None

# Instructions models
class InstructionsUpdate(BaseModel):
    instructions: str

class InstructionsResponse(BaseModel):
    success: bool
    message: str
    instructions: Optional[str] = None

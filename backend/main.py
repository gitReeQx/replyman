from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.routes import auth, chat, files, training, instructions

settings = get_settings()

app = FastAPI(
    title="ReplyMan API",
    description="Backend for AI Business Assistant",
    version="1.0.0"
)

# CORS - разрешаем запросы с фронтенда
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://replyman.ru",
        "http://replyman.ru",
        "http://localhost:3000",
        "http://127.0.0.1:5500",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(files.router, prefix="/api/files", tags=["Files"])
app.include_router(training.router, prefix="/api/training", tags=["Training"])
app.include_router(instructions.router, prefix="/api/instructions", tags=["Instructions"])

@app.get("/")
async def root():
    return {"status": "ok", "service": "ReplyMan API"}

@app.get("/api/health")
async def health():
    return {"status": "healthy"}

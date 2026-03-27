from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    # Appwrite Configuration
    appwrite_endpoint: str = "https://api.ourbit.ru/v1"
    appwrite_project_id: str = "69c3dd6f00192d3c5b66"
    appwrite_api_key: str = "standard_d809f98f0befdd20506381cf7cd961f65306776125b05383818befcd48acd5c273292120f5fe9700831ae4028b6950547b80931334f4bce597983cef8567a4395cfd15f5c1f4fefddab1623259a744223ec88868b315b1086a7b9820512908b42c74ac82754d36109f5240b18919a9afc1f92d773849077a57aee3bf58af7b7f"
    appwrite_database_id: str = "ai-assistant-db"
    appwrite_users_collection_id: str = "users"
    appwrite_chats_collection_id: str = "chats"
    appwrite_files_bucket_id: str = "chat-files"
    
    # OpenAI Compatible API
    openai_base_url: str = "https://routerai.ru/api/v1"
    openai_api_key: str = "sk-94sIAhbB5hDHt60JvS_uLKs5SV8Tgrb7"
    openai_model: str = "qwen/qwen3.5-flash-02-23"
    
    # App Configuration
    secret_key: str = "t787hhd5fg5e5g5w5x3dgvc__iohvdb963287ds"
    app_url: str = "https://api.ourbit.ru:8000"
    frontend_url: str = "https://replyman.ru"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

@lru_cache()
def get_settings() -> Settings:
    return Settings()
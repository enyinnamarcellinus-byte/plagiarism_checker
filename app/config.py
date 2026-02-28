from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "sqlite:///./plagiarism.db"
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 8  # 8 hours

    redis_url: str = "redis://localhost:6379/0"
    upload_dir: str = "uploads"
    max_file_size_mb: int = 10

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra='ignore')


settings = Settings()
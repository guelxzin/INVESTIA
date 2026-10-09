from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./investia.db"
    secret_key: str = "dev-only-change-me"
    cors_origins: str = "http://localhost:8000"
    brapi_token: str = ""
    poll_seconds: int = 30

settings = Settings()

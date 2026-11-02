from functools import lru_cache
from urllib.parse import quote_plus
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables or .env file."""

    APP_NAME: str = "FastAPI MySQL WhatsApp Agent"
    DEBUG: bool = True

    # Individual MySQL / cPanel credentials (optional; overrides DATABASE_URL if DB_HOST is set)
    DB_HOST: str = ""
    DB_PORT: int = 3306
    DB_USER: str = ""
    DB_PASSWORD: str = ""
    DB_NAME: str = ""

    # Full SQLAlchemy URL fallback
    DATABASE_URL: str = "mysql+pymysql://root:password@localhost:3306/whatsapp_agent_db"

    # OpenAI / LLM settings (supports OpenAI, Groq, Gemini, OpenRouter, or local Ollama)
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str | None = None
    OPENAI_MODEL: str = "gpt-4o-mini"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def sqlalchemy_database_url(self) -> str:
        """Build safe SQLAlchemy URL (auto-escapes special characters in cPanel passwords)."""
        if self.DB_HOST and self.DB_USER and self.DB_NAME:
            encoded_user = quote_plus(self.DB_USER)
            encoded_password = quote_plus(self.DB_PASSWORD)
            return (
                f"mysql+pymysql://{encoded_user}:{encoded_password}"
                f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"
            )
        return self.DATABASE_URL


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()


settings = get_settings()


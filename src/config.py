from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Telegram
    TELEGRAM_BOT_TOKEN: str

    # Supabase
    SUPABASE_URL: str
    SUPABASE_KEY: str

    # OpenAI
    OPENAI_API_KEY: str
    OPENAI_MODEL: str = "gpt-5-mini-2025-08-07"

    # Scheduler (MSK timezone)
    REMINDER_MORNING_HOUR: int = 11
    REMINDER_EVENING_HOUR: int = 19
    TIMEZONE: str = "Europe/Moscow"

    # Defaults
    DEFAULT_FREQUENCY: str = "biweekly"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

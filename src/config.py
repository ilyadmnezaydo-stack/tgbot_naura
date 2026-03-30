from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Telegram
    TELEGRAM_BOT_TOKEN: str
    OWNER_USER_ID: int | None = None
    ADMIN_USER_IDS: list[int] = Field(default_factory=list)

    # Supabase
    SUPABASE_URL: str
    SUPABASE_KEY: str

    # CloudPayments / SBP
    CLOUDPAYMENTS_PUBLIC_ID: str = ""
    CLOUDPAYMENTS_API_SECRET: str = ""
    CLOUDPAYMENTS_SBP_CURRENCY: str = "RUB"
    CLOUDPAYMENTS_SBP_TTL_MINUTES: int = 180
    CLOUDPAYMENTS_TEST_MODE: bool = False
    CLOUDPAYMENTS_SUCCESS_REDIRECT_URL: str = ""
    CLOUDPAYMENTS_TIMEOUT_SECONDS: int = 20

    # Local/OpenAI-compatible LLM
    LLM_BASE_URL: str = Field(
        default="http://localhost:11434/v1",
        validation_alias=AliasChoices("LLM_BASE_URL", "OPENAI_BASE_URL"),
    )
    LLM_API_KEY: str = Field(
        default="local",
        validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY"),
    )
    LLM_MODEL: str = Field(
        default="qwen2.5:7b",
        validation_alias=AliasChoices("LLM_MODEL", "OPENAI_MODEL"),
    )

    # Speech-to-text
    TRANSCRIPTION_REMOTE_ENABLED: bool = True
    TRANSCRIPTION_BASE_URL: str = ""
    TRANSCRIPTION_API_KEY: str = ""
    TRANSCRIPTION_MODEL: str = "whisper-1"
    TRANSCRIPTION_LANGUAGE: str = "ru"
    TRANSCRIPTION_TIMEOUT_SECONDS: int = 180
    TRANSCRIPTION_MAX_FILE_MB: int = 25
    TRANSCRIPTION_LOCAL_FALLBACK_ENABLED: bool = True
    TRANSCRIPTION_LOCAL_MODEL: str = "base"
    TRANSCRIPTION_LOCAL_DEVICE: str = "cpu"
    TRANSCRIPTION_LOCAL_COMPUTE_TYPE: str = "int8"
    TRANSCRIPTION_LOCAL_CPU_THREADS: int = 4

    # Scheduler (MSK timezone)
    REMINDER_MORNING_HOUR: int = 11
    REMINDER_EVENING_HOUR: int = 19
    TIMEZONE: str = "Europe/Moscow"

    # Defaults
    DEFAULT_FREQUENCY: str = "biweekly"

    @field_validator("ADMIN_USER_IDS", mode="before")
    @classmethod
    def parse_admin_user_ids(cls, value):
        if value in (None, ""):
            return []
        if isinstance(value, int):
            return [value]
        if isinstance(value, str):
            return [int(item.strip()) for item in value.split(",") if item.strip()]
        if isinstance(value, (list, tuple, set)):
            return [int(item) for item in value]
        raise TypeError("ADMIN_USER_IDS must be a comma-separated string or a list of ints")

    @property
    def all_admin_user_ids(self) -> list[int]:
        ids: list[int] = []
        if self.OWNER_USER_ID is not None:
            ids.append(self.OWNER_USER_ID)
        ids.extend(self.ADMIN_USER_IDS)
        return list(dict.fromkeys(ids))

    @property
    def cloudpayments_enabled(self) -> bool:
        return bool(self.CLOUDPAYMENTS_PUBLIC_ID and self.CLOUDPAYMENTS_API_SECRET)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

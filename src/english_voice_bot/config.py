from __future__ import annotations

import json
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: SecretStr
    openrouter_api_key: SecretStr

    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_chat_model: str = "openai/gpt-4o-mini"
    openrouter_chat_fallback_models: Annotated[tuple[str, ...], NoDecode] = (
        "google/gemini-2.5-flash-lite",
    )
    openrouter_stt_model: str = "openai/gpt-4o-mini-transcribe"
    openrouter_tts_model: str = "hexgrad/kokoro-82m"
    openrouter_tts_voice: str = "af_heart"
    openrouter_tts_speed: float = 1.0

    database_url: str = "sqlite+aiosqlite:///./data/bot.sqlite3"

    max_context_messages: int = Field(default=30, ge=1, le=200)
    max_review_messages: int = Field(default=100, ge=1, le=500)
    question_bank_path: str = "./questions.json"
    question_bank_include_builtin: bool = False
    reminder_timezone: str = "UTC"
    reminder_check_interval_seconds: int = Field(default=30, ge=5, le=3600)
    reminder_parse_max_attempts: int = Field(default=3, ge=1, le=10)
    goal_parse_max_attempts: int = Field(default=3, ge=1, le=10)

    allowed_telegram_user_ids: Annotated[frozenset[int], NoDecode] = Field(
        default_factory=frozenset
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @field_validator("allowed_telegram_user_ids", mode="before")
    @classmethod
    def parse_allowed_user_ids(cls, value: object) -> frozenset[int]:
        if value is None or value == "":
            return frozenset()
        if isinstance(value, frozenset):
            return value
        if isinstance(value, set | list | tuple):
            return frozenset(cls.parse_allowed_user_id(item) for item in value)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return frozenset()
            if stripped.startswith("["):
                decoded = json.loads(stripped)
                if not isinstance(decoded, list):
                    raise ValueError("ALLOWED_TELEGRAM_USER_IDS JSON value must be a list")
                return frozenset(cls.parse_allowed_user_id(item) for item in decoded)
            return frozenset(
                cls.parse_allowed_user_id(part.strip())
                for part in stripped.split(",")
                if part.strip()
            )
        raise ValueError("ALLOWED_TELEGRAM_USER_IDS must be a comma-separated list of integers")

    @field_validator("openrouter_chat_fallback_models", mode="before")
    @classmethod
    def parse_openrouter_chat_fallback_models(cls, value: object) -> tuple[str, ...]:
        if value is None or value == "":
            return ()
        if isinstance(value, tuple):
            return value
        if isinstance(value, list | set):
            return tuple(cls.parse_openrouter_chat_model(item) for item in value)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return ()
            if stripped.startswith("["):
                decoded = json.loads(stripped)
                if not isinstance(decoded, list):
                    raise ValueError("OPENROUTER_CHAT_FALLBACK_MODELS JSON value must be a list")
                return tuple(cls.parse_openrouter_chat_model(item) for item in decoded)
            return tuple(
                cls.parse_openrouter_chat_model(part.strip())
                for part in stripped.split(",")
                if part.strip()
            )
        raise ValueError("OPENROUTER_CHAT_FALLBACK_MODELS must be a comma-separated list")

    @classmethod
    def parse_allowed_user_id(cls, value: object) -> int:
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "ALLOWED_TELEGRAM_USER_IDS must contain numeric Telegram user IDs, "
                "not Telegram usernames"
            ) from exc

    @staticmethod
    def parse_openrouter_chat_model(value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("OPENROUTER_CHAT_FALLBACK_MODELS must contain model IDs")
        return value.strip()

    @property
    def openrouter_api_key_value(self) -> str:
        return self.openrouter_api_key.get_secret_value()

    @property
    def telegram_bot_token_value(self) -> str:
        return self.telegram_bot_token.get_secret_value()

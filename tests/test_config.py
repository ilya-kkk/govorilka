from __future__ import annotations

import pytest

from english_voice_bot.config import Settings


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        telegram_bot_token="telegram-token",
        openrouter_api_key="openrouter-key",
    )


def test_allowed_telegram_user_ids_accepts_comma_separated_env(monkeypatch) -> None:
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123456789, 987654321")

    settings = make_settings()

    assert settings.allowed_telegram_user_ids == frozenset({123456789, 987654321})


def test_allowed_telegram_user_ids_accepts_json_array_env(monkeypatch) -> None:
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "[123456789, 987654321]")

    settings = make_settings()

    assert settings.allowed_telegram_user_ids == frozenset({123456789, 987654321})


def test_allowed_telegram_user_ids_rejects_usernames(monkeypatch) -> None:
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "telegram_username")

    with pytest.raises(ValueError, match="numeric Telegram user IDs"):
        make_settings()

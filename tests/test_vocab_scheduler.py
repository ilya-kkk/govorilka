from __future__ import annotations

from datetime import UTC, datetime

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from english_vocab_bot.config import VocabularySettings
from english_vocab_bot.models import Base
from english_vocab_bot.repositories import get_or_create_user
from english_vocab_bot.services.scheduler import send_due_daily_messages


class FakeMessage:
    def __init__(self, message_id: int) -> None:
        self.message_id = message_id


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    async def send_message(self, **kwargs: object) -> FakeMessage:
        self.messages.append(kwargs)
        return FakeMessage(len(self.messages))


@pytest_asyncio.fixture
async def vocab_session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


def make_settings(**overrides: object) -> VocabularySettings:
    values = {
        "vocab_bot_token": "telegram-token",
        "openrouter_api_key": "openrouter-key",
    }
    values.update(overrides)
    return VocabularySettings(_env_file=None, **values)


async def test_send_due_daily_messages_sends_once_after_moscow_10(
    vocab_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot = FakeBot()
    settings = make_settings()
    async with vocab_session_factory() as db:
        await get_or_create_user(db, telegram_chat_id=10, telegram_user_id=20)
        await db.commit()

    before_due = datetime(2026, 7, 6, 6, 59, tzinfo=UTC)
    due = datetime(2026, 7, 6, 7, 0, tzinfo=UTC)

    before_count = await send_due_daily_messages(bot, vocab_session_factory, settings=settings, now=before_due)
    first_count = await send_due_daily_messages(bot, vocab_session_factory, settings=settings, now=due)
    second_count = await send_due_daily_messages(bot, vocab_session_factory, settings=settings, now=due)

    assert before_count == 0
    assert first_count == 1
    assert second_count == 0
    assert len(bot.messages) == 1
    assert bot.messages[0]["chat_id"] == 10
    assert "Словарик за 06.07.2026" in str(bot.messages[0]["text"])

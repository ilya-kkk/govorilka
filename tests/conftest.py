from __future__ import annotations

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from english_voice_bot.config import Settings
from english_voice_bot.models import Base


@pytest_asyncio.fixture
async def session_factory() -> async_sessionmaker[AsyncSession]:
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


def make_settings(**overrides: object) -> Settings:
    values = {
        "telegram_bot_token": "telegram-token",
        "openrouter_api_key": "openrouter-key",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)

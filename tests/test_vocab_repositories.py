from __future__ import annotations

from datetime import date

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from english_vocab_bot.models import Base
from english_vocab_bot.repositories import (
    add_words_to_day,
    get_or_create_day,
    get_or_create_user,
    list_day_entries,
    mark_day_downloaded,
)


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


async def test_add_words_to_day_deduplicates_case_insensitively(
    vocab_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with vocab_session_factory() as db:
        user = await get_or_create_user(db, telegram_chat_id=10, telegram_user_id=20)
        day = await get_or_create_day(db, user_id=user.id, local_date=date(2026, 7, 6))

        await add_words_to_day(db, day=day, words=["Chapter", "chapter", "feel anxious"])
        entries = await list_day_entries(db, day_id=day.id)

    assert [entry.text for entry in entries] == ["Chapter", "feel anxious"]


async def test_adding_new_word_after_download_reenables_day(
    vocab_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with vocab_session_factory() as db:
        user = await get_or_create_user(db, telegram_chat_id=10, telegram_user_id=20)
        day = await get_or_create_day(db, user_id=user.id, local_date=date(2026, 7, 6))
        await mark_day_downloaded(db, day=day)

        await add_words_to_day(db, day=day, words=["burden"])

    assert day.downloaded_at is None

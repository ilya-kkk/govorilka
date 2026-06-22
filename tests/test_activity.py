from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from english_voice_bot.repositories import get_or_create_session, list_practice_daily_stats
from english_voice_bot.services.activity import count_words, format_duration, record_practice_activity


def test_count_words_handles_plain_text() -> None:
    assert count_words("Hello, I can't use RAG well yet.") == 7


def test_format_duration() -> None:
    assert format_duration(0) == "0 мин"
    assert format_duration(15 * 60) == "15 мин"
    assert format_duration(75 * 60) == "1 ч 15 мин"


async def test_record_practice_activity_rebuilds_daily_stats(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        session = await get_or_create_session(db, telegram_chat_id=1, telegram_user_id=2)
        for index, occurred_at in enumerate(
            [
                datetime(2026, 6, 22, 9, 0, tzinfo=UTC),
                datetime(2026, 6, 22, 9, 10, tzinfo=UTC),
                datetime(2026, 6, 22, 9, 30, tzinfo=UTC),
                datetime(2026, 6, 22, 9, 44, tzinfo=UTC),
            ],
            start=1,
        ):
            await record_practice_activity(
                db,
                session_id=session.id,
                telegram_message_id=index,
                source_type="text",
                content="hello English",
                timezone="UTC",
                occurred_at=occurred_at,
            )

        rows = await list_practice_daily_stats(db, session_id=session.id)

    assert len(rows) == 1
    assert rows[0].message_count == 4
    assert rows[0].word_count == 8
    assert rows[0].practice_seconds == 24 * 60

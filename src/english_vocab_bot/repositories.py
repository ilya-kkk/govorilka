from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from english_vocab_bot.models import VocabDay, VocabEntry, VocabUser, utc_now


def normalize_vocab_text(text: str) -> str:
    return text.lower().strip()


async def get_or_create_user(
    db: AsyncSession,
    *,
    telegram_chat_id: int,
    telegram_user_id: int,
) -> VocabUser:
    result = await db.execute(
        select(VocabUser).where(
            VocabUser.telegram_chat_id == telegram_chat_id,
            VocabUser.telegram_user_id == telegram_user_id,
        )
    )
    user = result.scalar_one_or_none()
    if user is not None:
        user.updated_at = utc_now()
        await db.flush()
        return user

    user = VocabUser(
        telegram_chat_id=telegram_chat_id,
        telegram_user_id=telegram_user_id,
    )
    db.add(user)
    await db.flush()
    return user


async def list_users(db: AsyncSession) -> list[VocabUser]:
    result = await db.execute(select(VocabUser).order_by(VocabUser.id.asc()))
    return list(result.scalars().all())


async def get_or_create_day(
    db: AsyncSession,
    *,
    user_id: int,
    local_date: date,
) -> VocabDay:
    result = await db.execute(
        select(VocabDay).where(
            VocabDay.user_id == user_id,
            VocabDay.local_date == local_date,
        )
    )
    day = result.scalar_one_or_none()
    if day is not None:
        day.updated_at = utc_now()
        await db.flush()
        return day

    day = VocabDay(user_id=user_id, local_date=local_date)
    db.add(day)
    await db.flush()
    return day


async def get_day_for_user(
    db: AsyncSession,
    *,
    day_id: int,
    telegram_user_id: int,
) -> VocabDay | None:
    result = await db.execute(
        select(VocabDay)
        .join(VocabUser)
        .where(
            VocabDay.id == day_id,
            VocabUser.telegram_user_id == telegram_user_id,
        )
    )
    return result.scalar_one_or_none()


async def list_day_entries(db: AsyncSession, *, day_id: int) -> list[VocabEntry]:
    result = await db.execute(
        select(VocabEntry)
        .where(VocabEntry.day_id == day_id)
        .order_by(VocabEntry.id.asc())
    )
    return list(result.scalars().all())


async def add_words_to_day(
    db: AsyncSession,
    *,
    day: VocabDay,
    words: Sequence[str],
) -> list[VocabEntry]:
    result = await db.execute(
        select(VocabEntry.normalized_text).where(VocabEntry.day_id == day.id)
    )
    existing = set(result.scalars().all())
    added: list[VocabEntry] = []

    for raw_word in words:
        word = raw_word.strip()
        normalized = normalize_vocab_text(word)
        if not word or not normalized or normalized in existing:
            continue

        entry = VocabEntry(day_id=day.id, text=word, normalized_text=normalized)
        db.add(entry)
        added.append(entry)
        existing.add(normalized)

    if added and day.downloaded_at is not None:
        day.downloaded_at = None
    if added:
        day.updated_at = utc_now()
    await db.flush()
    return added


async def update_day_summary_message_id(
    db: AsyncSession,
    *,
    day: VocabDay,
    message_id: int,
) -> None:
    day.summary_message_id = message_id
    day.updated_at = utc_now()
    await db.flush()


async def mark_day_downloaded(db: AsyncSession, *, day: VocabDay) -> None:
    day.downloaded_at = utc_now()
    day.updated_at = utc_now()
    await db.flush()

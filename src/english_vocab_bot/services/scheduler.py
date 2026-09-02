from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from english_vocab_bot.config import VocabularySettings
from english_vocab_bot.db import session_scope
from english_vocab_bot.handlers.guards import is_allowed_user
from english_vocab_bot.repositories import get_or_create_day, list_day_entries, list_users, update_day_summary_message_id
from english_vocab_bot.formatting import format_daily_vocab_message
from english_vocab_bot.keyboards import download_keyboard
from english_vocab_bot.services.time import local_now

logger = logging.getLogger(__name__)


async def run_daily_vocab_scheduler(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    settings: VocabularySettings,
) -> None:
    while True:
        try:
            await send_due_daily_messages(bot, session_factory, settings=settings)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Vocabulary scheduler tick failed")
        await asyncio.sleep(settings.vocab_scheduler_interval_seconds)


async def send_due_daily_messages(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    settings: VocabularySettings,
    now: datetime | None = None,
) -> int:
    current_local_time = local_now(settings, now)
    if (current_local_time.hour, current_local_time.minute) < (
        settings.vocab_daily_hour,
        settings.vocab_daily_minute,
    ):
        return 0

    sent_count = 0
    async with session_scope(session_factory) as db:
        users = await list_users(db)
        for user in users:
            if not is_allowed_user(user.telegram_user_id, settings):
                continue

            day = await get_or_create_day(db, user_id=user.id, local_date=current_local_time.date())
            if day.summary_message_id is not None:
                continue

            entries = await list_day_entries(db, day_id=day.id)
            words = [entry.text for entry in entries]
            try:
                message = await bot.send_message(
                    chat_id=user.telegram_chat_id,
                    text=format_daily_vocab_message(day.local_date, words),
                    reply_markup=None if day.downloaded_at is not None else download_keyboard(day.id),
                )
            except TelegramAPIError:
                logger.exception(
                    "Vocabulary daily message send failed",
                    extra={"day_id": day.id, "chat_id": user.telegram_chat_id},
                )
                continue

            await update_day_summary_message_id(db, day=day, message_id=message.message_id)
            sent_count += 1

        await db.commit()

    return sent_count

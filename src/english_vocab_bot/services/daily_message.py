from __future__ import annotations

import logging
from datetime import date

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from english_vocab_bot.formatting import format_daily_vocab_message
from english_vocab_bot.keyboards import download_keyboard
from english_vocab_bot.models import VocabDay, VocabUser
from english_vocab_bot.repositories import (
    get_or_create_day,
    get_or_create_user,
    list_day_entries,
    update_day_summary_message_id,
)

logger = logging.getLogger(__name__)


async def ensure_daily_message(
    bot: Bot,
    db: AsyncSession,
    *,
    telegram_chat_id: int,
    telegram_user_id: int,
    local_date: date,
) -> VocabDay:
    user = await get_or_create_user(
        db,
        telegram_chat_id=telegram_chat_id,
        telegram_user_id=telegram_user_id,
    )
    day = await get_or_create_day(db, user_id=user.id, local_date=local_date)
    await refresh_day_summary(bot, db, user=user, day=day)
    return day


async def refresh_day_summary(
    bot: Bot,
    db: AsyncSession,
    *,
    user: VocabUser,
    day: VocabDay,
) -> None:
    entries = await list_day_entries(db, day_id=day.id)
    words = [entry.text for entry in entries]
    text = format_daily_vocab_message(day.local_date, words)
    reply_markup = None if day.downloaded_at is not None else download_keyboard(day.id)

    if day.summary_message_id is not None:
        try:
            await bot.edit_message_text(
                chat_id=user.telegram_chat_id,
                message_id=day.summary_message_id,
                text=text,
                reply_markup=reply_markup,
            )
            return
        except TelegramAPIError:
            logger.info(
                "Could not edit vocabulary summary; sending a new message",
                exc_info=True,
                extra={"day_id": day.id, "chat_id": user.telegram_chat_id},
            )

    message = await bot.send_message(
        chat_id=user.telegram_chat_id,
        text=text,
        reply_markup=reply_markup,
    )
    await update_day_summary_message_id(db, day=day, message_id=message.message_id)

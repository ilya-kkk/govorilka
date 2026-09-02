from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from english_vocab_bot.config import VocabularySettings
from english_vocab_bot.db import session_scope
from english_vocab_bot.handlers.guards import reject_message_if_not_allowed
from english_vocab_bot.parser import parse_words
from english_vocab_bot.repositories import add_words_to_day, get_or_create_day, get_or_create_user
from english_vocab_bot.services.daily_message import refresh_day_summary
from english_vocab_bot.services.time import local_today

logger = logging.getLogger(__name__)
router = Router()


@router.message(F.text)
async def text_words_handler(
    message: Message,
    bot: Bot,
    settings: VocabularySettings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if message.text and message.text.startswith("/"):
        return
    if await reject_message_if_not_allowed(message, settings):
        return
    if message.from_user is None or not message.text:
        return

    words = parse_words(message.text)
    if not words:
        await _safe_delete_message(message)
        return

    async with session_scope(session_factory) as db:
        user = await get_or_create_user(
            db,
            telegram_chat_id=message.chat.id,
            telegram_user_id=message.from_user.id,
        )
        day = await get_or_create_day(db, user_id=user.id, local_date=local_today(settings))
        await add_words_to_day(db, day=day, words=words)
        await refresh_day_summary(bot, db, user=user, day=day)
        await db.commit()

    await _safe_delete_message(message)


async def _safe_delete_message(message: Message) -> None:
    try:
        await message.delete()
    except TelegramAPIError:
        logger.debug("Could not delete vocabulary input message", exc_info=True)

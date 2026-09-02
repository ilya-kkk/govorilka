from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from english_vocab_bot.config import VocabularySettings
from english_vocab_bot.db import session_scope
from english_vocab_bot.handlers.guards import reject_message_if_not_allowed
from english_vocab_bot.services.daily_message import ensure_daily_message
from english_vocab_bot.services.time import local_today

router = Router()

START_TEXT = (
    "Готов собирать словарик. Присылай английские слова или фразы отдельными строками, "
    "а я буду обновлять один список за сегодня."
)

HELP_TEXT = """/start - зарегистрировать чат и показать сегодняшний словарик
/today - показать или восстановить сегодняшний словарик
/help - показать команды

Присылай слова обычным сообщением. Я добавлю новые, удалю твое сообщение и обновлю список.
Кнопка «Скачать .apkg» соберет Anki-колоду за выбранный день."""


@router.message(CommandStart())
async def start_command(
    message: Message,
    bot: Bot,
    settings: VocabularySettings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if await reject_message_if_not_allowed(message, settings):
        return
    if message.from_user is None:
        return

    await message.answer(START_TEXT)
    await _ensure_today_summary(message, bot, settings, session_factory)


@router.message(Command("help"))
async def help_command(message: Message, settings: VocabularySettings) -> None:
    if await reject_message_if_not_allowed(message, settings):
        return
    await message.answer(HELP_TEXT)


@router.message(Command("today"))
async def today_command(
    message: Message,
    bot: Bot,
    settings: VocabularySettings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if await reject_message_if_not_allowed(message, settings):
        return
    await _ensure_today_summary(message, bot, settings, session_factory)


async def _ensure_today_summary(
    message: Message,
    bot: Bot,
    settings: VocabularySettings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if message.from_user is None:
        return
    async with session_scope(session_factory) as db:
        await ensure_daily_message(
            bot,
            db,
            telegram_chat_id=message.chat.id,
            telegram_user_id=message.from_user.id,
            local_date=local_today(settings),
        )
        await db.commit()

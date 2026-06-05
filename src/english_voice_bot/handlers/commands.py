from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from english_voice_bot.config import Settings
from english_voice_bot.db import session_scope
from english_voice_bot.handlers.guards import reject_message_if_not_allowed
from english_voice_bot.keyboards import REVIEW_BUTTON_TEXT, dialogue_reply_keyboard
from english_voice_bot.repositories import clear_session_dialogue, get_or_create_session
from english_voice_bot.services.openrouter import OpenRouterClient, OpenRouterError
from english_voice_bot.services.review import run_review_flow

logger = logging.getLogger(__name__)
router = Router()
REVIEW_ERROR = "⚠️ I could not generate a review. Please try again in a moment."
REVIEW_STATUS = "🔎 Checking your messages..."

START_TEXT = """Send a voice message in English.

I will return the transcription so you can check whether your speech was understood, then I will answer with a voice message.

The written answer is hidden under a spoiler. Press 🔍 Find my mistakes when you want a review."""

HELP_TEXT = """/start - Show the quick intro
/help - Show commands
/review - Review new learner messages
/reset - Clear this dialogue

You can send voice messages for practice or ordinary text messages for debugging and occasional practice."""


@router.message(CommandStart())
async def start_command(message: Message, settings: Settings) -> None:
    if await reject_message_if_not_allowed(message, settings):
        return
    await message.answer(START_TEXT, reply_markup=dialogue_reply_keyboard())


@router.message(Command("help"))
async def help_command(message: Message, settings: Settings) -> None:
    if await reject_message_if_not_allowed(message, settings):
        return
    await message.answer(HELP_TEXT, reply_markup=dialogue_reply_keyboard())


@router.message(F.text == REVIEW_BUTTON_TEXT)
async def review_reply_button(
    message: Message,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    openrouter_client: OpenRouterClient,
) -> None:
    await run_review_for_message(
        message=message,
        settings=settings,
        session_factory=session_factory,
        openrouter_client=openrouter_client,
    )


@router.message(Command("review"))
async def review_command(
    message: Message,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    openrouter_client: OpenRouterClient,
) -> None:
    await run_review_for_message(
        message=message,
        settings=settings,
        session_factory=session_factory,
        openrouter_client=openrouter_client,
    )


async def run_review_for_message(
    *,
    message: Message,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    openrouter_client: OpenRouterClient,
) -> None:
    if await reject_message_if_not_allowed(message, settings):
        return

    status = await message.answer(REVIEW_STATUS)
    status_deleted = False

    async with session_scope(session_factory) as db:
        session = await get_or_create_session(
            db,
            telegram_chat_id=message.chat.id,
            telegram_user_id=message.from_user.id,
        )
        await db.commit()

        async def send_html(text: str) -> None:
            nonlocal status_deleted
            if not status_deleted:
                await _safe_delete_status(status)
                status_deleted = True
            await message.answer(text, parse_mode=ParseMode.MARKDOWN_V2)

        try:
            await run_review_flow(
                db,
                session_id=session.id,
                openrouter_client=openrouter_client,
                settings=settings,
                send_html=send_html,
            )
        except OpenRouterError:
            await db.rollback()
            await _safe_edit_status(status, REVIEW_ERROR)


@router.message(Command("reset"))
async def reset_command(
    message: Message,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if await reject_message_if_not_allowed(message, settings):
        return

    async with session_scope(session_factory) as db:
        session = await get_or_create_session(
            db,
            telegram_chat_id=message.chat.id,
            telegram_user_id=message.from_user.id,
        )
        deleted_count = await clear_session_dialogue(db, session_id=session.id)
        await db.commit()

    await message.answer(f"🧹 Dialogue history cleared. Removed {deleted_count} messages.")


async def _safe_edit_status(status: Message, text: str) -> None:
    try:
        await status.edit_text(text)
    except TelegramAPIError:
        await status.answer(text)


async def _safe_delete_status(status: Message) -> None:
    try:
        await status.delete()
    except TelegramAPIError:
        logger.debug("Could not delete temporary status message", exc_info=True)

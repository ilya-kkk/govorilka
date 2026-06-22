from __future__ import annotations

import io
import logging

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from english_voice_bot.config import Settings
from english_voice_bot.db import session_scope
from english_voice_bot.formatting import format_transcription
from english_voice_bot.handlers.guards import reject_message_if_not_allowed
from english_voice_bot.keyboards import ASK_ME_BUTTON_TEXT, RESET_BUTTON_TEXT, REVIEW_BUTTON_TEXT, SETTINGS_BUTTON_TEXT
from english_voice_bot.repositories import (
    ROLE_ASSISTANT,
    ROLE_USER,
    SOURCE_GENERATED,
    SOURCE_TEXT,
    SOURCE_VOICE,
    add_dialogue_message,
    get_or_create_session,
)
from english_voice_bot.services.activity import record_practice_activity
from english_voice_bot.services.conversation import generate_assistant_reply, send_assistant_response
from english_voice_bot.services.openrouter import OpenRouterClient, OpenRouterError

logger = logging.getLogger(__name__)
router = Router()

DOWNLOAD_ERROR = "⚠️ I could not download the voice message. Please try again."
STT_ERROR = "⚠️ I could not transcribe that message. Please record it again."
EMPTY_TRANSCRIPTION_ERROR = "⚠️ I could not hear any speech clearly. Please try again."
LLM_ERROR = "⚠️ I could not generate a reply. Please try again in a moment."
GENERATING_REPLY_STATUS = "💬 Preparing a reply..."


@router.message(F.voice)
async def voice_message_handler(
    message: Message,
    bot: Bot,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    openrouter_client: OpenRouterClient,
) -> None:
    if await reject_message_if_not_allowed(message, settings):
        return

    status = await message.answer("🎧 Transcribing...")
    try:
        audio_bytes = await _download_voice_bytes(bot, message)
    except TelegramAPIError:
        logger.exception("Telegram voice download failed")
        await _safe_edit_status(status, DOWNLOAD_ERROR)
        return

    try:
        transcription = await openrouter_client.transcribe_ogg(audio_bytes)
    except OpenRouterError:
        logger.exception("STT failed")
        await _safe_edit_status(status, STT_ERROR)
        return

    if not transcription.strip():
        await _safe_edit_status(status, EMPTY_TRANSCRIPTION_ERROR)
        return

    await _safe_delete_status(status)
    await message.reply(format_transcription(transcription), parse_mode=ParseMode.HTML)
    reply_status = await message.answer(GENERATING_REPLY_STATUS)
    await _process_user_message(
        message=message,
        settings=settings,
        session_factory=session_factory,
        openrouter_client=openrouter_client,
        content=transcription,
        source_type=SOURCE_VOICE,
        status=reply_status,
    )


@router.message(F.text)
async def text_message_handler(
    message: Message,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    openrouter_client: OpenRouterClient,
) -> None:
    if message.text and message.text.startswith("/"):
        return
    if message.text in {REVIEW_BUTTON_TEXT, ASK_ME_BUTTON_TEXT, SETTINGS_BUTTON_TEXT, RESET_BUTTON_TEXT}:
        return
    if await reject_message_if_not_allowed(message, settings):
        return
    if not message.text or not message.text.strip():
        return

    status = await message.answer(GENERATING_REPLY_STATUS)
    await _process_user_message(
        message=message,
        settings=settings,
        session_factory=session_factory,
        openrouter_client=openrouter_client,
        content=message.text.strip(),
        source_type=SOURCE_TEXT,
        status=status,
    )


async def _download_voice_bytes(bot: Bot, message: Message) -> bytes:
    if message.voice is None:
        raise TelegramAPIError(method=None, message="Missing voice payload")
    buffer = io.BytesIO()
    await bot.download(message.voice.file_id, destination=buffer)
    return buffer.getvalue()


async def _process_user_message(
    *,
    message: Message,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    openrouter_client: OpenRouterClient,
    content: str,
    source_type: str,
    status: Message | None = None,
) -> None:
    async with session_scope(session_factory) as db:
        session = await get_or_create_session(
            db,
            telegram_chat_id=message.chat.id,
            telegram_user_id=message.from_user.id,
        )
        await add_dialogue_message(
            db,
            session_id=session.id,
            telegram_message_id=message.message_id,
            role=ROLE_USER,
            source_type=source_type,
            content=content,
        )
        await record_practice_activity(
            db,
            session_id=session.id,
            telegram_message_id=message.message_id,
            source_type=source_type,
            content=content,
            timezone=settings.reminder_timezone,
        )
        await db.commit()

        try:
            assistant_text = await generate_assistant_reply(
                db,
                session_id=session.id,
                openrouter_client=openrouter_client,
                settings=settings,
            )
        except OpenRouterError:
            logger.exception("Chat completion failed")
            if status is not None:
                await _safe_edit_status(status, LLM_ERROR)
            else:
                await message.answer(LLM_ERROR)
            return

        await add_dialogue_message(
            db,
            session_id=session.id,
            telegram_message_id=None,
            role=ROLE_ASSISTANT,
            source_type=SOURCE_GENERATED,
            content=assistant_text,
        )
        await db.commit()

    await send_assistant_response(
        message,
        assistant_text=assistant_text,
        openrouter_client=openrouter_client,
    )
    if status is not None:
        await _safe_delete_status(status)


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

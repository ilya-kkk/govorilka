from __future__ import annotations

import logging
from collections.abc import Sequence

from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession

from english_voice_bot.config import Settings
from english_voice_bot.formatting import format_spoiler_text
from english_voice_bot.keyboards import dialogue_actions_keyboard, dialogue_reply_keyboard
from english_voice_bot.prompts import CONVERSATION_SYSTEM_PROMPT
from english_voice_bot.repositories import get_recent_conversation_context
from english_voice_bot.services.openrouter import OpenRouterClient, OpenRouterError

logger = logging.getLogger(__name__)

TTS_FALLBACK_WARNING = "⚠️ Voice generation failed, so I sent only the written answer."


def build_chat_messages(history: Sequence[object]) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": CONVERSATION_SYSTEM_PROMPT}]
    for item in history:
        role = getattr(item, "role")
        content = getattr(item, "content")
        if role in {"user", "assistant"}:
            messages.append({"role": role, "content": content})
    return messages


async def generate_assistant_reply(
    db: AsyncSession,
    *,
    session_id: int,
    openrouter_client: OpenRouterClient,
    settings: Settings,
) -> str:
    history = await get_recent_conversation_context(
        db,
        session_id=session_id,
        limit=settings.max_context_messages,
    )
    return await openrouter_client.chat_completion(build_chat_messages(history), temperature=0.7)


async def send_assistant_response(
    message: Message,
    *,
    assistant_text: str,
    openrouter_client: OpenRouterClient,
) -> bool:
    voice_sent = False
    try:
        audio_bytes = await openrouter_client.synthesize_speech_mp3(assistant_text)
    except OpenRouterError:
        logger.exception("TTS generation failed")
    else:
        try:
            await message.answer_voice(
                voice=BufferedInputFile(audio_bytes, filename="answer.mp3"),
                reply_markup=dialogue_reply_keyboard(),
            )
            voice_sent = True
        except TelegramAPIError:
            logger.exception("Telegram voice send failed")

    spoiler = format_spoiler_text(assistant_text)
    if not voice_sent:
        spoiler = f"{spoiler}\n\n{TTS_FALLBACK_WARNING}"

    await message.answer(
        spoiler,
        parse_mode=ParseMode.HTML,
        reply_markup=dialogue_actions_keyboard() if voice_sent else dialogue_reply_keyboard(),
    )
    return voice_sent

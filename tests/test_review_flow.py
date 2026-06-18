from __future__ import annotations

import pytest
from aiogram.types import ReplyKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from english_voice_bot.keyboards import (
    CONFIRM_REMINDERS_BUTTON_TEXT,
    RESET_BUTTON_TEXT,
    REVIEW_BUTTON_TEXT,
    SETTINGS_BUTTON_TEXT,
    reminder_confirmation_keyboard,
)
from english_voice_bot.models import DialogueMessage
from english_voice_bot.repositories import (
    ROLE_ASSISTANT,
    ROLE_USER,
    SOURCE_GENERATED,
    SOURCE_TEXT,
    add_dialogue_message,
    get_or_create_session,
)
from english_voice_bot.services.conversation import TTS_FALLBACK_WARNING, send_assistant_response
from english_voice_bot.services.openrouter import OpenRouterError
from english_voice_bot.services.review import run_review_flow
from tests.conftest import make_settings


class FakeOpenRouter:
    async def synthesize_speech_mp3(self, text: str) -> bytes:
        raise OpenRouterError("tts failed")

    async def chat_completion(self, messages: list[dict[str, str]], *, temperature: float = 0.7) -> str:
        return "<b>Report</b>"


class FakeSuccessfulTTSOpenRouter(FakeOpenRouter):
    async def synthesize_speech_mp3(self, text: str) -> bytes:
        return b"mp3"


class FakeMessage:
    def __init__(self) -> None:
        self.voice_calls: list[object] = []
        self.answer_calls: list[dict[str, object]] = []

    async def answer_voice(self, **kwargs: object) -> None:
        self.voice_calls.append(kwargs)

    async def answer(self, text: str, **kwargs: object) -> None:
        self.answer_calls.append({"text": text, **kwargs})


def test_reminder_confirmation_keyboard() -> None:
    markup = reminder_confirmation_keyboard()

    assert markup.inline_keyboard[0][0].text == CONFIRM_REMINDERS_BUTTON_TEXT
    assert markup.inline_keyboard[0][0].callback_data == "settings:reminders:confirm"


async def test_tts_failure_fallback_sends_hidden_written_answer() -> None:
    message = FakeMessage()

    voice_sent = await send_assistant_response(
        message,  # type: ignore[arg-type]
        assistant_text="Use <carefully> & listen",
        openrouter_client=FakeOpenRouter(),  # type: ignore[arg-type]
    )

    assert voice_sent is False
    assert message.voice_calls == []
    assert len(message.answer_calls) == 1
    sent_text = message.answer_calls[0]["text"]
    assert "<tg-spoiler>Use &lt;carefully&gt; &amp; listen</tg-spoiler>" in sent_text
    assert TTS_FALLBACK_WARNING in sent_text
    reply_markup = message.answer_calls[0]["reply_markup"]
    assert isinstance(reply_markup, ReplyKeyboardMarkup)
    assert reply_markup.keyboard[0][0].text == REVIEW_BUTTON_TEXT
    assert reply_markup.keyboard[0][1].text == SETTINGS_BUTTON_TEXT
    assert reply_markup.keyboard[0][2].text == RESET_BUTTON_TEXT


async def test_tts_success_sets_reply_keyboard_on_voice_and_text() -> None:
    message = FakeMessage()

    voice_sent = await send_assistant_response(
        message,  # type: ignore[arg-type]
        assistant_text="Use carefully",
        openrouter_client=FakeSuccessfulTTSOpenRouter(),  # type: ignore[arg-type]
    )

    assert voice_sent is True
    assert len(message.voice_calls) == 1
    assert message.voice_calls[0]["voice"].data == b"mp3"
    assert message.voice_calls[0]["voice"].filename == "answer.mp3"
    voice_markup = message.voice_calls[0]["reply_markup"]
    assert isinstance(voice_markup, ReplyKeyboardMarkup)
    assert voice_markup.keyboard[0][0].text == REVIEW_BUTTON_TEXT
    assert voice_markup.keyboard[0][1].text == SETTINGS_BUTTON_TEXT
    assert voice_markup.keyboard[0][2].text == RESET_BUTTON_TEXT

    assert len(message.answer_calls) == 1
    text_markup = message.answer_calls[0]["reply_markup"]
    assert isinstance(text_markup, ReplyKeyboardMarkup)
    assert text_markup.keyboard[0][0].text == REVIEW_BUTTON_TEXT
    assert text_markup.keyboard[0][1].text == SETTINGS_BUTTON_TEXT
    assert text_markup.keyboard[0][2].text == RESET_BUTTON_TEXT


async def test_review_failure_does_not_mark_messages_reviewed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        session = await get_or_create_session(db, telegram_chat_id=1, telegram_user_id=2)
        user_message = await add_dialogue_message(
            db,
            session_id=session.id,
            role=ROLE_USER,
            source_type=SOURCE_TEXT,
            content="I go to shop yesterday",
        )
        await add_dialogue_message(
            db,
            session_id=session.id,
            role=ROLE_ASSISTANT,
            source_type=SOURCE_GENERATED,
            content="What did you buy?",
        )
        await db.commit()

        async def failing_send_html(text: str) -> None:
            raise RuntimeError("telegram send failed")

        with pytest.raises(RuntimeError):
            await run_review_flow(
                db,
                session_id=session.id,
                openrouter_client=FakeOpenRouter(),  # type: ignore[arg-type]
                settings=make_settings(),
                send_html=failing_send_html,
            )

        refreshed = (
            await db.execute(select(DialogueMessage).where(DialogueMessage.id == user_message.id))
        ).scalar_one()

    assert refreshed.reviewed_at is None


async def test_successful_review_marks_messages_after_send(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    sent: list[str] = []
    async with session_factory() as db:
        session = await get_or_create_session(db, telegram_chat_id=1, telegram_user_id=2)
        user_message = await add_dialogue_message(
            db,
            session_id=session.id,
            role=ROLE_USER,
            source_type=SOURCE_TEXT,
            content="I go to shop yesterday",
        )
        await db.commit()

        async def send_html(text: str) -> None:
            sent.append(text)

        result = await run_review_flow(
            db,
            session_id=session.id,
            openrouter_client=FakeOpenRouter(),  # type: ignore[arg-type]
            settings=make_settings(),
            send_html=send_html,
        )

        refreshed = (
            await db.execute(select(DialogueMessage).where(DialogueMessage.id == user_message.id))
        ).scalar_one()

    assert sent == ["*Report*"]
    assert result.reviewed_count == 1
    assert refreshed.reviewed_at is not None

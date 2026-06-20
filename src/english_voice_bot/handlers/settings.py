from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import BaseFilter, Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from english_voice_bot.config import Settings
from english_voice_bot.db import session_scope
from english_voice_bot.handlers.guards import reject_callback_if_not_allowed, reject_message_if_not_allowed
from english_voice_bot.keyboards import (
    SETTINGS_BUTTON_TEXT,
    reminder_confirmation_keyboard,
    settings_inline_keyboard,
)
from english_voice_bot.repositories import (
    PENDING_ACTION_REMINDER_SETUP,
    clear_pending_user_action,
    clear_reminder_schedule_draft,
    get_pending_user_action,
    get_reminder_schedule_draft,
    set_pending_user_action,
    upsert_reminder_schedule_draft,
    upsert_reminder_schedule,
)
from english_voice_bot.services.openrouter import OpenRouterClient, OpenRouterError
from english_voice_bot.services.reminders import (
    format_reminder_confirmation,
    parse_reminder_request,
    reminder_plan_from_json,
    reminder_plan_to_json,
)

logger = logging.getLogger(__name__)
router = Router()

SETTINGS_TEXT = """Settings

You can configure the following options:"""
REMINDER_SETUP_PROMPT = """Напиши обычным текстом, когда тебе напоминать заниматься английским.

Например:
каждый день утром и вечером
или
по вторникам и пятницам в 19:30"""
REMINDER_PARSE_STATUS = "🧠 Разбираю расписание..."
REMINDER_PARSE_ERROR = "⚠️ Не смог разобрать расписание. Попробуй написать чуть конкретнее."
REMINDER_DRAFT_EXPIRED = "⚠️ Черновик настройки не найден. Нажми «Настроить напоминания» еще раз."


class PendingReminderSetupFilter(BaseFilter):
    async def __call__(
        self,
        message: Message,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> bool:
        if not message.text or message.text.startswith("/") or message.from_user is None:
            return False
        async with session_scope(session_factory) as db:
            pending = await get_pending_user_action(
                db,
                telegram_chat_id=message.chat.id,
                telegram_user_id=message.from_user.id,
            )
        return pending is not None and pending.action == PENDING_ACTION_REMINDER_SETUP


@router.message(Command("settings"))
async def settings_command(message: Message, settings: Settings) -> None:
    await show_settings(message, settings)


@router.message(F.text == SETTINGS_BUTTON_TEXT)
async def settings_reply_button(message: Message, settings: Settings) -> None:
    await show_settings(message, settings)


async def show_settings(message: Message, settings: Settings) -> None:
    if await reject_message_if_not_allowed(message, settings):
        return
    await message.answer(SETTINGS_TEXT, reply_markup=settings_inline_keyboard())


@router.callback_query(F.data == "settings:reminders")
async def reminders_settings_callback(
    callback: CallbackQuery,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await callback.answer()
    if await reject_callback_if_not_allowed(callback, settings, already_answered=True):
        return
    if callback.message is None:
        return

    async with session_scope(session_factory) as db:
        await set_pending_user_action(
            db,
            telegram_chat_id=callback.message.chat.id,
            telegram_user_id=callback.from_user.id,
            action=PENDING_ACTION_REMINDER_SETUP,
        )
        await db.commit()

    await callback.message.answer(REMINDER_SETUP_PROMPT)


@router.message(PendingReminderSetupFilter(), F.text)
async def reminder_setup_text_handler(
    message: Message,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    openrouter_client: OpenRouterClient,
) -> None:
    if await reject_message_if_not_allowed(message, settings):
        return
    if message.from_user is None or not message.text:
        return

    status = await message.answer(REMINDER_PARSE_STATUS)
    try:
        plan = await parse_reminder_request(
            openrouter_client,
            user_text=message.text.strip(),
            timezone=settings.reminder_timezone,
            max_attempts=settings.reminder_parse_max_attempts,
        )
    except (OpenRouterError, ValueError):
        logger.exception("Reminder schedule parsing failed")
        await _safe_edit_status(status, REMINDER_PARSE_ERROR)
        return

    async with session_scope(session_factory) as db:
        await upsert_reminder_schedule_draft(
            db,
            telegram_chat_id=message.chat.id,
            telegram_user_id=message.from_user.id,
            timezone=plan.timezone,
            schedule_json=reminder_plan_to_json(plan),
        )
        await clear_pending_user_action(
            db,
            telegram_chat_id=message.chat.id,
            telegram_user_id=message.from_user.id,
            action=PENDING_ACTION_REMINDER_SETUP,
        )
        await db.commit()

    await _safe_edit_status(
        status,
        format_reminder_confirmation(plan),
        reply_markup=reminder_confirmation_keyboard(),
    )


@router.callback_query(F.data == "settings:reminders:confirm")
async def confirm_reminders_callback(
    callback: CallbackQuery,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await callback.answer()
    if await reject_callback_if_not_allowed(callback, settings, already_answered=True):
        return
    if callback.message is None:
        return

    async with session_scope(session_factory) as db:
        draft = await get_reminder_schedule_draft(
            db,
            telegram_chat_id=callback.message.chat.id,
            telegram_user_id=callback.from_user.id,
        )
        if draft is None:
            await db.rollback()
            await _safe_edit_status(callback.message, REMINDER_DRAFT_EXPIRED, reply_markup=None)
            return

        try:
            plan = reminder_plan_from_json(draft.schedule_json)
        except ValueError:
            logger.exception("Reminder draft is invalid")
            await clear_reminder_schedule_draft(
                db,
                telegram_chat_id=callback.message.chat.id,
                telegram_user_id=callback.from_user.id,
            )
            await db.commit()
            await _safe_edit_status(callback.message, REMINDER_DRAFT_EXPIRED, reply_markup=None)
            return

        await upsert_reminder_schedule(
            db,
            telegram_chat_id=callback.message.chat.id,
            telegram_user_id=callback.from_user.id,
            timezone=plan.timezone,
            schedule_json=reminder_plan_to_json(plan),
            enabled=any(day.enabled for day in plan.days),
        )
        await clear_reminder_schedule_draft(
            db,
            telegram_chat_id=callback.message.chat.id,
            telegram_user_id=callback.from_user.id,
        )
        await db.commit()

    await _safe_edit_status(
        callback.message,
        f"{format_reminder_confirmation(plan)}\n\n✅ Настройка установлена.",
        reply_markup=None,
    )


async def _safe_edit_status(status: Message, text: str, **kwargs: object) -> None:
    try:
        await status.edit_text(text, **kwargs)
    except TelegramAPIError:
        await status.answer(text, **kwargs)

from __future__ import annotations

import logging
from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import BaseFilter, Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from english_voice_bot.config import Settings
from english_voice_bot.db import session_scope
from english_voice_bot.handlers.guards import reject_callback_if_not_allowed, reject_message_if_not_allowed
from english_voice_bot.keyboards import (
    goal_reminder_confirmation_keyboard,
    goal_status_keyboard,
)
from english_voice_bot.repositories import (
    PENDING_ACTION_GOAL_REMINDER_SETUP,
    PENDING_ACTION_GOAL_SETUP,
    clear_goal_reminder_schedule_draft,
    clear_pending_user_action,
    get_goal_reminder_schedule_draft,
    get_or_create_session,
    get_pending_user_action,
    get_practice_goal,
    set_pending_user_action,
    upsert_goal_reminder_schedule,
    upsert_goal_reminder_schedule_draft,
    upsert_practice_goal,
)
from english_voice_bot.services.activity import format_results_report
from english_voice_bot.services.goals import (
    format_goal_saved,
    format_goal_status_for_user,
    goal_to_json,
    parse_practice_goal_request,
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

GOAL_SETUP_PROMPT = """Напиши цель обычным текстом.

Например:
10 часов speaking practice в неделю
или
100 часов английского за 6 месяцев"""
GOAL_PARSE_STATUS = "🧠 Разбираю цель..."
GOAL_PARSE_ERROR = "⚠️ Не смог разобрать цель. Попробуй написать конкретнее: сколько часов и за какой период."
NO_GOAL_TEXT = "🎯 Цель пока не установлена. Используй /setgoal, чтобы её задать."
GOAL_REMINDER_SETUP_PROMPT = """Напиши, когда напоминать тебе о прогрессе по цели.

Например:
каждый день в 23:00
или
по воскресеньям вечером"""
GOAL_REMINDER_PARSE_STATUS = "🧠 Разбираю расписание напоминаний по цели..."
GOAL_REMINDER_PARSE_ERROR = "⚠️ Не смог разобрать расписание. Попробуй написать чуть конкретнее."
GOAL_REMINDER_DRAFT_EXPIRED = "⚠️ Черновик настройки не найден. Нажми «Установить напоминание» ещё раз."


class PendingGoalSetupFilter(BaseFilter):
    async def __call__(
        self,
        message: Message,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> bool:
        return await _has_pending_action(message, session_factory, PENDING_ACTION_GOAL_SETUP)


class PendingGoalReminderSetupFilter(BaseFilter):
    async def __call__(
        self,
        message: Message,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> bool:
        return await _has_pending_action(message, session_factory, PENDING_ACTION_GOAL_REMINDER_SETUP)


async def _has_pending_action(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    action: str,
) -> bool:
    if not message.text or message.text.startswith("/") or message.from_user is None:
        return False
    async with session_scope(session_factory) as db:
        pending = await get_pending_user_action(
            db,
            telegram_chat_id=message.chat.id,
            telegram_user_id=message.from_user.id,
        )
    return pending is not None and pending.action == action


@router.message(Command("showresults"))
async def show_results_command(
    message: Message,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if await reject_message_if_not_allowed(message, settings):
        return
    if message.from_user is None:
        return

    async with session_scope(session_factory) as db:
        session = await get_or_create_session(
            db,
            telegram_chat_id=message.chat.id,
            telegram_user_id=message.from_user.id,
        )
        report = await format_results_report(
            db,
            session_id=session.id,
            now=datetime.now(UTC),
            timezone=settings.reminder_timezone,
        )
    await message.answer(report)


@router.message(Command("setgoal"))
async def set_goal_command(
    message: Message,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if await reject_message_if_not_allowed(message, settings):
        return
    if message.from_user is None:
        return

    async with session_scope(session_factory) as db:
        await set_pending_user_action(
            db,
            telegram_chat_id=message.chat.id,
            telegram_user_id=message.from_user.id,
            action=PENDING_ACTION_GOAL_SETUP,
        )
        await db.commit()
    await message.answer(GOAL_SETUP_PROMPT)


@router.message(PendingGoalSetupFilter(), F.text)
async def goal_setup_text_handler(
    message: Message,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    openrouter_client: OpenRouterClient,
) -> None:
    if await reject_message_if_not_allowed(message, settings):
        return
    if message.from_user is None or not message.text:
        return

    status = await message.answer(GOAL_PARSE_STATUS)
    try:
        parsed_goal = await parse_practice_goal_request(
            openrouter_client,
            user_text=message.text.strip(),
            timezone=settings.reminder_timezone,
            max_attempts=settings.goal_parse_max_attempts,
        )
    except (OpenRouterError, ValueError):
        logger.exception("Practice goal parsing failed")
        await _safe_edit_status(status, GOAL_PARSE_ERROR)
        return

    async with session_scope(session_factory) as db:
        await upsert_practice_goal(
            db,
            telegram_chat_id=message.chat.id,
            telegram_user_id=message.from_user.id,
            goal_type=parsed_goal.goal_type,
            target_minutes=parsed_goal.target_minutes,
            period=parsed_goal.period,
            start_date=parsed_goal.start_date,
            deadline_date=parsed_goal.deadline_date,
            goal_json=goal_to_json(parsed_goal),
        )
        await clear_pending_user_action(
            db,
            telegram_chat_id=message.chat.id,
            telegram_user_id=message.from_user.id,
            action=PENDING_ACTION_GOAL_SETUP,
        )
        await db.commit()

    await _safe_edit_status(status, format_goal_saved(parsed_goal))


@router.message(Command("goalstatus"))
async def goal_status_command(
    message: Message,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if await reject_message_if_not_allowed(message, settings):
        return
    if message.from_user is None:
        return

    async with session_scope(session_factory) as db:
        goal = await get_practice_goal(
            db,
            telegram_chat_id=message.chat.id,
            telegram_user_id=message.from_user.id,
        )
        if goal is None:
            await message.answer(NO_GOAL_TEXT)
            return
        report = await format_goal_status_for_user(
            db,
            telegram_chat_id=message.chat.id,
            telegram_user_id=message.from_user.id,
            goal=goal,
            now=datetime.now(UTC),
            timezone=settings.reminder_timezone,
        )
    await message.answer(report, reply_markup=goal_status_keyboard())


@router.callback_query(F.data == "goals:reminders")
async def goal_reminders_callback(
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
        goal = await get_practice_goal(
            db,
            telegram_chat_id=callback.message.chat.id,
            telegram_user_id=callback.from_user.id,
        )
        if goal is None:
            await callback.message.answer(NO_GOAL_TEXT)
            return
        await set_pending_user_action(
            db,
            telegram_chat_id=callback.message.chat.id,
            telegram_user_id=callback.from_user.id,
            action=PENDING_ACTION_GOAL_REMINDER_SETUP,
        )
        await db.commit()
    await callback.message.answer(GOAL_REMINDER_SETUP_PROMPT)


@router.message(PendingGoalReminderSetupFilter(), F.text)
async def goal_reminder_setup_text_handler(
    message: Message,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    openrouter_client: OpenRouterClient,
) -> None:
    if await reject_message_if_not_allowed(message, settings):
        return
    if message.from_user is None or not message.text:
        return

    status = await message.answer(GOAL_REMINDER_PARSE_STATUS)
    try:
        plan = await parse_reminder_request(
            openrouter_client,
            user_text=message.text.strip(),
            timezone=settings.reminder_timezone,
            max_attempts=settings.reminder_parse_max_attempts,
        )
    except (OpenRouterError, ValueError):
        logger.exception("Goal reminder schedule parsing failed")
        await _safe_edit_status(status, GOAL_REMINDER_PARSE_ERROR)
        return

    async with session_scope(session_factory) as db:
        await upsert_goal_reminder_schedule_draft(
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
            action=PENDING_ACTION_GOAL_REMINDER_SETUP,
        )
        await db.commit()

    await _safe_edit_status(
        status,
        format_reminder_confirmation(plan),
        reply_markup=goal_reminder_confirmation_keyboard(),
    )


@router.callback_query(F.data == "goals:reminders:confirm")
async def confirm_goal_reminders_callback(
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
        draft = await get_goal_reminder_schedule_draft(
            db,
            telegram_chat_id=callback.message.chat.id,
            telegram_user_id=callback.from_user.id,
        )
        if draft is None:
            await db.rollback()
            await _safe_edit_status(callback.message, GOAL_REMINDER_DRAFT_EXPIRED, reply_markup=None)
            return

        try:
            plan = reminder_plan_from_json(draft.schedule_json)
        except ValueError:
            logger.exception("Goal reminder draft is invalid")
            await clear_goal_reminder_schedule_draft(
                db,
                telegram_chat_id=callback.message.chat.id,
                telegram_user_id=callback.from_user.id,
            )
            await db.commit()
            await _safe_edit_status(callback.message, GOAL_REMINDER_DRAFT_EXPIRED, reply_markup=None)
            return

        await upsert_goal_reminder_schedule(
            db,
            telegram_chat_id=callback.message.chat.id,
            telegram_user_id=callback.from_user.id,
            timezone=plan.timezone,
            schedule_json=reminder_plan_to_json(plan),
            enabled=any(day.enabled for day in plan.days),
        )
        await clear_goal_reminder_schedule_draft(
            db,
            telegram_chat_id=callback.message.chat.id,
            telegram_user_id=callback.from_user.id,
        )
        await db.commit()

    await _safe_edit_status(
        callback.message,
        f"{format_reminder_confirmation(plan)}\n\n✅ Напоминание по цели установлено.",
        reply_markup=None,
    )


async def _safe_edit_status(status: Message, text: str, **kwargs: object) -> None:
    try:
        await status.edit_text(text, **kwargs)
    except TelegramAPIError:
        await status.answer(text, **kwargs)

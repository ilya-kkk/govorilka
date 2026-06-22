from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from english_voice_bot.db import session_scope
from english_voice_bot.keyboards import dialogue_reply_keyboard
from english_voice_bot.repositories import (
    get_practice_goal,
    list_enabled_goal_reminder_schedules,
    list_enabled_reminder_schedules,
    update_goal_reminder_last_sent_slot,
    update_reminder_last_sent_slot,
)
from english_voice_bot.services.goals import format_goal_status_for_user
from english_voice_bot.services.reminders import due_slot_for_now, reminder_plan_from_json

logger = logging.getLogger(__name__)

REMINDER_TEXT = """⏰ Time for English practice.

Send me a voice message in English when you have a minute."""


async def run_reminder_scheduler(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    interval_seconds: int,
) -> None:
    while True:
        try:
            await send_due_reminders(bot, session_factory)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Reminder scheduler tick failed")
        await asyncio.sleep(interval_seconds)


async def send_due_reminders(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
) -> int:
    if now is None:
        now = datetime.now(UTC)

    sent_count = 0
    async with session_scope(session_factory) as db:
        schedules = await list_enabled_reminder_schedules(db)
        for schedule in schedules:
            try:
                plan = reminder_plan_from_json(schedule.schedule_json)
                due_slot = due_slot_for_now(plan, now)
            except (ValueError, TypeError):
                logger.exception("Invalid reminder schedule", extra={"schedule_id": schedule.id})
                continue

            if due_slot is None or due_slot == schedule.last_sent_slot:
                continue

            try:
                await bot.send_message(
                    chat_id=schedule.telegram_chat_id,
                    text=REMINDER_TEXT,
                    reply_markup=dialogue_reply_keyboard(),
                )
            except TelegramAPIError:
                logger.exception(
                    "Reminder send failed",
                    extra={"schedule_id": schedule.id, "chat_id": schedule.telegram_chat_id},
                )
                continue

            await update_reminder_last_sent_slot(db, schedule_id=schedule.id, last_sent_slot=due_slot)
            sent_count += 1

        goal_schedules = await list_enabled_goal_reminder_schedules(db)
        for schedule in goal_schedules:
            try:
                plan = reminder_plan_from_json(schedule.schedule_json)
                due_slot = due_slot_for_now(plan, now)
            except (ValueError, TypeError):
                logger.exception("Invalid goal reminder schedule", extra={"schedule_id": schedule.id})
                continue

            if due_slot is None or due_slot == schedule.last_sent_slot:
                continue

            goal = await get_practice_goal(
                db,
                telegram_chat_id=schedule.telegram_chat_id,
                telegram_user_id=schedule.telegram_user_id,
            )
            if goal is None:
                continue

            try:
                text = await format_goal_status_for_user(
                    db,
                    telegram_chat_id=schedule.telegram_chat_id,
                    telegram_user_id=schedule.telegram_user_id,
                    goal=goal,
                    now=now,
                    timezone=schedule.timezone,
                    reminder_period=infer_goal_reminder_period(plan),
                )
                await bot.send_message(
                    chat_id=schedule.telegram_chat_id,
                    text=text,
                    reply_markup=dialogue_reply_keyboard(),
                )
            except TelegramAPIError:
                logger.exception(
                    "Goal reminder send failed",
                    extra={"schedule_id": schedule.id, "chat_id": schedule.telegram_chat_id},
                )
                continue

            await update_goal_reminder_last_sent_slot(db, schedule_id=schedule.id, last_sent_slot=due_slot)
            sent_count += 1

        await db.commit()

    return sent_count


def infer_goal_reminder_period(plan: object) -> str:
    days = getattr(plan, "days")
    enabled_days = sum(1 for day in days if getattr(day, "enabled"))
    return "day" if enabled_days >= 5 else "week"

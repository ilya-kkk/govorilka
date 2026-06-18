from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from english_voice_bot.repositories import get_reminder_schedule, upsert_reminder_schedule
from english_voice_bot.services.reminder_scheduler import send_due_reminders
from english_voice_bot.services.reminders import ReminderDay, ReminderPlan, reminder_plan_to_json


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    async def send_message(self, **kwargs: object) -> None:
        self.messages.append(kwargs)


def make_schedule_json() -> str:
    plan = ReminderPlan(
        timezone="UTC",
        days=(
            ReminderDay("monday", False, ()),
            ReminderDay("tuesday", True, ("09:00",)),
            ReminderDay("wednesday", False, ()),
            ReminderDay("thursday", False, ()),
            ReminderDay("friday", False, ()),
            ReminderDay("saturday", False, ()),
            ReminderDay("sunday", False, ()),
        ),
        assumptions=(),
    )
    return reminder_plan_to_json(plan)


async def test_send_due_reminders_sends_once_per_slot(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot = FakeBot()
    async with session_factory() as db:
        await upsert_reminder_schedule(
            db,
            telegram_chat_id=10,
            telegram_user_id=20,
            timezone="UTC",
            schedule_json=make_schedule_json(),
        )
        await db.commit()

    now = datetime(2026, 6, 16, 9, 0, 30, tzinfo=UTC)
    first_count = await send_due_reminders(bot, session_factory, now=now)  # type: ignore[arg-type]
    second_count = await send_due_reminders(bot, session_factory, now=now)  # type: ignore[arg-type]

    async with session_factory() as db:
        schedule = await get_reminder_schedule(db, telegram_chat_id=10, telegram_user_id=20)

    assert first_count == 1
    assert second_count == 0
    assert len(bot.messages) == 1
    assert bot.messages[0]["chat_id"] == 10
    assert schedule is not None
    assert schedule.last_sent_slot == "2026-06-16:09:00"

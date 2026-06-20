from __future__ import annotations

from datetime import UTC, datetime

import pytest

from english_voice_bot.services.reminders import (
    ReminderDay,
    ReminderPlan,
    due_slot_for_now,
    format_reminder_confirmation,
    parse_reminder_request,
    parse_reminder_plan,
    reminder_plan_from_json,
    reminder_plan_to_json,
)
from english_voice_bot.services.openrouter import OpenRouterError


class FakeReminderOpenRouter:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = responses
        self.messages_by_call: list[list[dict[str, str]]] = []

    async def chat_completion_json_schema(
        self,
        messages: list[dict[str, str]],
        *,
        schema_name: str,
        schema: dict[str, object],
        temperature: float = 0.1,
    ) -> dict[str, object]:
        self.messages_by_call.append(messages)
        return self.responses.pop(0)


def make_plan() -> ReminderPlan:
    return ReminderPlan(
        timezone="UTC",
        days=(
            ReminderDay("monday", False, ()),
            ReminderDay("tuesday", True, ("09:00", "19:00")),
            ReminderDay("wednesday", False, ()),
            ReminderDay("thursday", False, ()),
            ReminderDay("friday", True, ("09:00",)),
            ReminderDay("saturday", False, ()),
            ReminderDay("sunday", False, ()),
        ),
        assumptions=("Два раза в неделю интерпретировано как вторник и пятница.",),
    )


def test_reminder_plan_round_trip_and_confirmation() -> None:
    plan = make_plan()

    restored = reminder_plan_from_json(reminder_plan_to_json(plan))
    text = format_reminder_confirmation(restored)

    assert restored == plan
    assert "Понедельник: нет" in text
    assert "Вторник: 09:00, 19:00" in text
    assert "Пятница: 09:00" in text
    assert "Часовой пояс: UTC" in text
    assert "Допущения:" in text


def test_due_slot_for_matching_minute() -> None:
    plan = make_plan()

    due_slot = due_slot_for_now(plan, datetime(2026, 6, 16, 9, 0, 30, tzinfo=UTC))

    assert due_slot == "2026-06-16:09:00"


def test_due_slot_returns_none_when_not_scheduled() -> None:
    plan = make_plan()

    due_slot = due_slot_for_now(plan, datetime(2026, 6, 18, 9, 0, tzinfo=UTC))

    assert due_slot is None


def test_parse_reminder_plan_requires_ordered_weekdays() -> None:
    data = {
        "timezone": "UTC",
        "days": [
            {"day": "tuesday", "enabled": False, "times": []},
            {"day": "monday", "enabled": False, "times": []},
            {"day": "wednesday", "enabled": False, "times": []},
            {"day": "thursday", "enabled": False, "times": []},
            {"day": "friday", "enabled": False, "times": []},
            {"day": "saturday", "enabled": False, "times": []},
            {"day": "sunday", "enabled": False, "times": []},
        ],
        "assumptions": [],
    }

    with pytest.raises(ValueError, match="Monday through Sunday"):
        parse_reminder_plan(data)


async def test_parse_reminder_request_retries_invalid_structured_json() -> None:
    client = FakeReminderOpenRouter(
        [
            {
                "timezone": "UTC",
                "days": [
                    {"day": "monday", "enabled": True, "times": ["09:00"]},
                ],
                "assumptions": [],
            },
            {
                "timezone": "UTC",
                "days": [
                    {"day": "monday", "enabled": False, "times": []},
                    {"day": "tuesday", "enabled": True, "times": ["09:00"]},
                    {"day": "wednesday", "enabled": False, "times": []},
                    {"day": "thursday", "enabled": False, "times": []},
                    {"day": "friday", "enabled": True, "times": ["19:00"]},
                    {"day": "saturday", "enabled": False, "times": []},
                    {"day": "sunday", "enabled": False, "times": []},
                ],
                "assumptions": ["Два раза в неделю выбраны вторник и пятница."],
            },
        ]
    )

    plan = await parse_reminder_request(
        client,  # type: ignore[arg-type]
        user_text="два раза в неделю утром и вечером",
        timezone="UTC",
        max_attempts=3,
    )

    assert plan.days[1].times == ("09:00",)
    assert plan.days[4].times == ("19:00",)
    assert len(client.messages_by_call) == 2
    assert "Previous structured-output attempt failed" in client.messages_by_call[1][-1]["content"]
    assert "exactly seven days" in client.messages_by_call[1][-1]["content"]


async def test_parse_reminder_request_raises_after_max_attempts() -> None:
    client = FakeReminderOpenRouter(
        [
            {"timezone": "UTC", "days": [], "assumptions": []},
            {"timezone": "UTC", "days": [], "assumptions": []},
            {"timezone": "UTC", "days": [], "assumptions": []},
        ]
    )

    with pytest.raises(OpenRouterError, match="after 3 attempts"):
        await parse_reminder_request(
            client,  # type: ignore[arg-type]
            user_text="каждый день утром",
            timezone="UTC",
            max_attempts=3,
        )

    assert len(client.messages_by_call) == 3

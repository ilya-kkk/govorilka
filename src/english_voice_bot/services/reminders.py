from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from english_voice_bot.services.openrouter import OpenRouterClient, OpenRouterError

logger = logging.getLogger(__name__)

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DAY_LABELS_RU = {
    "monday": "Понедельник",
    "tuesday": "Вторник",
    "wednesday": "Среда",
    "thursday": "Четверг",
    "friday": "Пятница",
    "saturday": "Суббота",
    "sunday": "Воскресенье",
}
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


@dataclass(frozen=True)
class ReminderDay:
    day: str
    enabled: bool
    times: tuple[str, ...]


@dataclass(frozen=True)
class ReminderPlan:
    timezone: str
    days: tuple[ReminderDay, ...]
    assumptions: tuple[str, ...]


def reminder_schema(*, timezone: str) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["timezone", "days", "assumptions"],
        "properties": {
            "timezone": {
                "type": "string",
                "enum": [timezone],
                "description": "The IANA timezone used for all reminder times.",
            },
            "days": {
                "type": "array",
                "minItems": 7,
                "maxItems": 7,
                "description": "Exactly seven days, Monday through Sunday.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["day", "enabled", "times"],
                    "properties": {
                        "day": {
                            "type": "string",
                            "enum": list(WEEKDAYS),
                            "description": "Lowercase English weekday name.",
                        },
                        "enabled": {
                            "type": "boolean",
                            "description": "Whether reminders are enabled on this weekday.",
                        },
                        "times": {
                            "type": "array",
                            "description": "Reminder times for this day in 24-hour HH:MM format.",
                            "items": {
                                "type": "string",
                                "pattern": r"^(?:[01]\d|2[0-3]):[0-5]\d$",
                            },
                            "maxItems": 5,
                        },
                    },
                },
            },
            "assumptions": {
                "type": "array",
                "description": "Short Russian notes about defaults used for vague user wording.",
                "items": {"type": "string"},
                "maxItems": 5,
            },
        },
    }


async def parse_reminder_request(
    openrouter_client: OpenRouterClient,
    *,
    user_text: str,
    timezone: str,
    max_attempts: int = 3,
) -> ReminderPlan:
    _validate_timezone(timezone)
    attempts = max(1, max_attempts)
    previous_error: str | None = None
    previous_data: dict[str, Any] | None = None
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            data = await openrouter_client.chat_completion_json_schema(
                _build_reminder_messages(
                    user_text=user_text,
                    timezone=timezone,
                    previous_error=previous_error,
                    previous_data=previous_data,
                ),
                schema_name="english_practice_reminder_schedule",
                schema=reminder_schema(timezone=timezone),
                temperature=0.1,
            )
        except OpenRouterError as exc:
            last_error = exc
            previous_error = str(exc)
            previous_data = None
            logger.warning(
                "Reminder structured-output request failed",
                extra={"attempt": attempt, "max_attempts": attempts},
                exc_info=True,
            )
            continue

        try:
            return parse_reminder_plan(data)
        except ValueError as exc:
            last_error = exc
            previous_error = str(exc)
            previous_data = data
            logger.warning(
                "Reminder structured-output JSON failed validation",
                extra={
                    "attempt": attempt,
                    "max_attempts": attempts,
                    "validation_error": previous_error,
                },
            )

    raise OpenRouterError(f"Could not parse reminder schedule after {attempts} attempts") from last_error


def _build_reminder_messages(
    *,
    user_text: str,
    timezone: str,
    previous_error: str | None,
    previous_data: dict[str, Any] | None,
) -> list[dict[str, str]]:
    messages = [
        {
            "role": "system",
            "content": (
                "You extract concrete English-practice reminder schedules from Russian or English user text. "
                "Return only JSON that matches the supplied schema. "
                "Use 24-hour HH:MM times. Use the provided timezone exactly. "
                "Always return exactly seven days in Monday-to-Sunday order. "
                "If the user says every day, enable all seven days. "
                "If the user gives a vague time, use these defaults: morning=09:00, day/afternoon=14:00, "
                "evening=19:00. If the user gives a frequency without exact weekdays, choose reasonable "
                "practice days and explain that choice in assumptions. For twice per week, prefer Tuesday "
                "and Friday. For three times per week, prefer Monday, Wednesday, and Friday. "
                "If the request is too unclear to schedule, disable all days and explain what is missing."
            ),
        },
        {
            "role": "user",
            "content": f"Timezone: {timezone}\nReminder request: {user_text}",
        },
    ]
    if previous_error is not None:
        retry_lines = [
            "Previous structured-output attempt failed local validation.",
            f"Validation error: {previous_error}",
            "Try again for the same reminder request. Return a corrected JSON object.",
            "The JSON must contain exactly seven days in this order: monday, tuesday, wednesday, thursday, friday, saturday, sunday.",
        ]
        if previous_data is not None:
            retry_lines.extend(
                [
                    "Previous invalid JSON:",
                    _compact_json_for_prompt(previous_data),
                ]
            )
        messages.append({"role": "user", "content": "\n".join(retry_lines)})
    return messages


def _compact_json_for_prompt(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)[:2000]


def parse_reminder_plan(data: dict[str, Any]) -> ReminderPlan:
    timezone = data.get("timezone")
    if not isinstance(timezone, str):
        raise ValueError("Reminder timezone must be a string")
    _validate_timezone(timezone)

    raw_days = data.get("days")
    if not isinstance(raw_days, list) or len(raw_days) != len(WEEKDAYS):
        raise ValueError("Reminder plan must contain exactly seven days")

    days: list[ReminderDay] = []
    for expected_day, raw_day in zip(WEEKDAYS, raw_days, strict=True):
        if not isinstance(raw_day, dict):
            raise ValueError("Reminder day must be an object")
        day = raw_day.get("day")
        enabled = raw_day.get("enabled")
        times = raw_day.get("times")
        if day != expected_day:
            raise ValueError("Reminder days must be ordered Monday through Sunday")
        if not isinstance(enabled, bool):
            raise ValueError("Reminder day enabled flag must be boolean")
        if not isinstance(times, list):
            raise ValueError("Reminder times must be a list")
        normalized_times = tuple(sorted(_validate_time(value) for value in times))
        if enabled and not normalized_times:
            raise ValueError("Enabled reminder days must contain at least one time")
        if not enabled and normalized_times:
            raise ValueError("Disabled reminder days must not contain times")
        days.append(ReminderDay(day=day, enabled=enabled, times=normalized_times))

    raw_assumptions = data.get("assumptions")
    if not isinstance(raw_assumptions, list):
        raise ValueError("Reminder assumptions must be a list")
    assumptions = tuple(item.strip() for item in raw_assumptions if isinstance(item, str) and item.strip())
    return ReminderPlan(timezone=timezone, days=tuple(days), assumptions=assumptions)


def reminder_plan_to_json(plan: ReminderPlan) -> str:
    return json.dumps(
        {
            "timezone": plan.timezone,
            "days": [
                {
                    "day": day.day,
                    "enabled": day.enabled,
                    "times": list(day.times),
                }
                for day in plan.days
            ],
            "assumptions": list(plan.assumptions),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def reminder_plan_from_json(value: str) -> ReminderPlan:
    data = json.loads(value)
    if not isinstance(data, dict):
        raise ValueError("Reminder JSON must be an object")
    return parse_reminder_plan(data)


def format_reminder_confirmation(plan: ReminderPlan) -> str:
    lines = ["✅ Окей, я понял так:", ""]
    for day in plan.days:
        label = DAY_LABELS_RU[day.day]
        value = ", ".join(day.times) if day.enabled else "нет"
        lines.append(f"{label}: {value}")
    lines.extend(["", f"Часовой пояс: {plan.timezone}"])
    if plan.assumptions:
        lines.extend(["", "Допущения:"])
        lines.extend(f"- {assumption}" for assumption in plan.assumptions)
    return "\n".join(lines)


def due_slot_for_now(plan: ReminderPlan, now: datetime | None = None) -> str | None:
    if now is None:
        now = datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    local_now = now.astimezone(ZoneInfo(plan.timezone))
    current_day = WEEKDAYS[local_now.weekday()]
    current_time = f"{local_now.hour:02}:{local_now.minute:02}"
    for day in plan.days:
        if day.day == current_day and day.enabled and current_time in day.times:
            return f"{local_now.date().isoformat()}:{current_time}"
    return None


def _validate_time(value: object) -> str:
    if not isinstance(value, str) or not TIME_RE.match(value):
        raise ValueError("Reminder time must be HH:MM")
    return value


def _validate_timezone(timezone: str) -> None:
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown reminder timezone: {timezone}") from exc

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from english_voice_bot.models import PracticeGoal
from english_voice_bot.repositories import get_or_create_session
from english_voice_bot.services.activity import format_duration, get_practice_totals, next_month_start
from english_voice_bot.services.openrouter import OpenRouterClient, OpenRouterError

logger = logging.getLogger(__name__)

GOAL_TYPE_PERIODIC = "periodic"
GOAL_TYPE_TOTAL = "total"
PERIOD_WEEK = "week"
PERIOD_MONTH = "month"
PERIOD_NONE = "none"


@dataclass(frozen=True)
class ParsedPracticeGoal:
    goal_type: str
    target_minutes: int
    period: str
    start_date: date
    deadline_date: date | None
    assumptions: tuple[str, ...]


@dataclass(frozen=True)
class GoalPeriod:
    start_date: date
    end_date: date
    label: str


def goal_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["goal_type", "target_hours", "period", "deadline_date", "assumptions"],
        "properties": {
            "goal_type": {
                "type": "string",
                "enum": [GOAL_TYPE_PERIODIC, GOAL_TYPE_TOTAL],
                "description": "periodic for recurring weekly/monthly goals, total for a one-time goal by deadline.",
            },
            "target_hours": {
                "type": "number",
                "minimum": 0.25,
                "maximum": 10000,
                "description": "Target amount of speaking practice in hours.",
            },
            "period": {
                "type": "string",
                "enum": [PERIOD_WEEK, PERIOD_MONTH, PERIOD_NONE],
                "description": "week or month for periodic goals; none for total goals.",
            },
            "deadline_date": {
                "type": "string",
                "description": "YYYY-MM-DD for total goals, or empty string for periodic goals.",
            },
            "assumptions": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 5,
                "description": "Short Russian notes about defaults or relative-date interpretation.",
            },
        },
    }


async def parse_practice_goal_request(
    openrouter_client: OpenRouterClient,
    *,
    user_text: str,
    timezone: str,
    now: datetime | None = None,
    max_attempts: int = 3,
) -> ParsedPracticeGoal:
    if now is None:
        now = datetime.now(UTC)
    local_today = now.astimezone(ZoneInfo(timezone)).date()
    attempts = max(1, max_attempts)
    previous_error: str | None = None
    previous_data: dict[str, Any] | None = None
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            data = await openrouter_client.chat_completion_json_schema(
                _build_goal_messages(
                    user_text=user_text,
                    timezone=timezone,
                    today=local_today,
                    previous_error=previous_error,
                    previous_data=previous_data,
                ),
                schema_name="english_practice_goal",
                schema=goal_schema(),
                temperature=0.1,
            )
        except OpenRouterError as exc:
            last_error = exc
            previous_error = str(exc)
            previous_data = None
            logger.warning(
                "Goal structured-output request failed",
                extra={"attempt": attempt, "max_attempts": attempts},
                exc_info=True,
            )
            continue

        try:
            return parse_practice_goal(data, start_date=local_today)
        except ValueError as exc:
            last_error = exc
            previous_error = str(exc)
            previous_data = data
            logger.warning(
                "Goal structured-output JSON failed validation",
                extra={"attempt": attempt, "max_attempts": attempts, "validation_error": previous_error},
            )

    raise OpenRouterError(f"Could not parse practice goal after {attempts} attempts") from last_error


def parse_practice_goal(data: dict[str, Any], *, start_date: date) -> ParsedPracticeGoal:
    goal_type = data.get("goal_type")
    if goal_type not in {GOAL_TYPE_PERIODIC, GOAL_TYPE_TOTAL}:
        raise ValueError("Goal type must be periodic or total")

    target_hours = data.get("target_hours")
    if not isinstance(target_hours, int | float) or target_hours <= 0:
        raise ValueError("Goal target_hours must be a positive number")
    target_minutes = max(1, round(float(target_hours) * 60))

    period = data.get("period")
    if period not in {PERIOD_WEEK, PERIOD_MONTH, PERIOD_NONE}:
        raise ValueError("Goal period must be week, month, or none")

    raw_deadline = data.get("deadline_date")
    if not isinstance(raw_deadline, str):
        raise ValueError("Goal deadline_date must be a string")
    deadline = date.fromisoformat(raw_deadline) if raw_deadline.strip() else None

    if goal_type == GOAL_TYPE_PERIODIC:
        if period not in {PERIOD_WEEK, PERIOD_MONTH}:
            raise ValueError("Periodic goals must use week or month period")
        if deadline is not None:
            raise ValueError("Periodic goals must not use deadline_date")
    else:
        if period != PERIOD_NONE:
            raise ValueError("Total goals must use period=none")
        if deadline is None:
            raise ValueError("Total goals require deadline_date")
        if deadline < start_date:
            raise ValueError("Goal deadline_date cannot be in the past")

    raw_assumptions = data.get("assumptions")
    if not isinstance(raw_assumptions, list):
        raise ValueError("Goal assumptions must be a list")
    assumptions = tuple(item.strip() for item in raw_assumptions if isinstance(item, str) and item.strip())
    return ParsedPracticeGoal(
        goal_type=goal_type,
        target_minutes=target_minutes,
        period=period,
        start_date=start_date,
        deadline_date=deadline,
        assumptions=assumptions,
    )


def goal_to_json(goal: ParsedPracticeGoal) -> str:
    return json.dumps(
        {
            "goal_type": goal.goal_type,
            "target_minutes": goal.target_minutes,
            "period": goal.period,
            "start_date": goal.start_date.isoformat(),
            "deadline_date": goal.deadline_date.isoformat() if goal.deadline_date else "",
            "assumptions": list(goal.assumptions),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def format_goal_saved(goal: ParsedPracticeGoal) -> str:
    lines = ["🎯 Цель установлена.", ""]
    lines.append(f"Объём: {format_duration(goal.target_minutes * 60)}")
    if goal.goal_type == GOAL_TYPE_PERIODIC:
        period_label = "в неделю" if goal.period == PERIOD_WEEK else "в месяц"
        lines.append(f"Тип: регулярно {period_label}")
    else:
        lines.append(f"Тип: до {goal.deadline_date:%Y-%m-%d}")
    if goal.assumptions:
        lines.extend(["", "Допущения:"])
        lines.extend(f"- {assumption}" for assumption in goal.assumptions)
    lines.extend(["", "Проверить прогресс можно командой /goalstatus."])
    return "\n".join(lines)


async def format_goal_status_for_user(
    db: AsyncSession,
    *,
    telegram_chat_id: int,
    telegram_user_id: int,
    goal: PracticeGoal,
    now: datetime,
    timezone: str,
    reminder_period: str | None = None,
) -> str:
    session = await get_or_create_session(
        db,
        telegram_chat_id=telegram_chat_id,
        telegram_user_id=telegram_user_id,
    )
    base_period = goal_period_for_now(goal, now=now, timezone=timezone)
    period = goal_period_for_now(goal, now=now, timezone=timezone, reminder_period=reminder_period)
    totals = await get_practice_totals(
        db,
        session_id=session.id,
        start_date=period.start_date,
        end_date=period.end_date,
    )
    target_seconds = target_seconds_for_period(
        total_target_seconds=goal.target_minutes * 60,
        base_period=base_period,
        period=period,
    )
    progress = min(999, (totals.seconds / target_seconds * 100) if target_seconds else 0)
    remaining = max(0, target_seconds - totals.seconds)
    expected_seconds = expected_progress_seconds(
        target_seconds=target_seconds,
        period_start=period.start_date,
        period_end=period.end_date,
        now=now,
        timezone=timezone,
    )

    lines = [
        "🎯 Статус цели",
        "",
        f"Период: {period.label}",
        f"Факт: {format_duration(totals.seconds)}",
        f"Цель: {format_duration(target_seconds)}",
        f"Прогресс: {progress:.0f}%",
    ]
    if remaining:
        lines.append(f"Осталось: {format_duration(remaining)}")
    else:
        lines.append("Цель уже закрыта на этот период.")

    lines.extend(["", goal_motivation_text(actual_seconds=totals.seconds, expected_seconds=expected_seconds)])
    return "\n".join(lines)


def goal_period_for_now(
    goal: PracticeGoal,
    *,
    now: datetime,
    timezone: str,
    reminder_period: str | None = None,
) -> GoalPeriod:
    local_today = now.astimezone(ZoneInfo(timezone)).date()
    if reminder_period == "day":
        return GoalPeriod(local_today, local_today, "сегодня")
    if reminder_period == "week":
        start = local_today - timedelta(days=local_today.weekday())
        return GoalPeriod(start, start + timedelta(days=6), "эта неделя")

    if goal.goal_type == GOAL_TYPE_PERIODIC and goal.period == PERIOD_WEEK:
        start = local_today - timedelta(days=local_today.weekday())
        return GoalPeriod(start, start + timedelta(days=6), "эта неделя")
    if goal.goal_type == GOAL_TYPE_PERIODIC and goal.period == PERIOD_MONTH:
        start = local_today.replace(day=1)
        return GoalPeriod(start, next_month_start(start) - timedelta(days=1), "этот месяц")
    deadline = goal.deadline_date or local_today
    return GoalPeriod(goal.start_date, deadline, f"{goal.start_date:%Y-%m-%d} - {deadline:%Y-%m-%d}")


def goal_motivation_text(*, actual_seconds: int, expected_seconds: int) -> str:
    if actual_seconds >= expected_seconds:
        return "Идёшь с опережением графика. Просто продолжай в том же темпе."
    if expected_seconds <= 0:
        return "Старт есть. Дальше будем смотреть динамику по мере практики."
    ratio = actual_seconds / expected_seconds
    if ratio >= 0.75:
        return "Ты немного ниже графика, но отставание небольшое. Ещё одна короткая сессия хорошо подтянет темп."
    return "Сейчас темп ниже цели. Мягко докинь одну-две практики в ближайшие дни, и график станет заметно спокойнее."


def expected_progress_seconds(
    *,
    target_seconds: int,
    period_start: date,
    period_end: date,
    now: datetime,
    timezone: str,
) -> int:
    local_now = now.astimezone(ZoneInfo(timezone))
    period_start_dt = datetime.combine(period_start, datetime.min.time(), tzinfo=local_now.tzinfo)
    period_end_dt = datetime.combine(period_end + timedelta(days=1), datetime.min.time(), tzinfo=local_now.tzinfo)
    if local_now <= period_start_dt:
        return 0
    if local_now >= period_end_dt:
        return target_seconds
    elapsed = (local_now - period_start_dt).total_seconds()
    total = (period_end_dt - period_start_dt).total_seconds()
    return round(target_seconds * elapsed / total)


def target_seconds_for_period(
    *,
    total_target_seconds: int,
    base_period: GoalPeriod,
    period: GoalPeriod,
) -> int:
    if base_period.start_date == period.start_date and base_period.end_date == period.end_date:
        return total_target_seconds

    overlap_start = max(base_period.start_date, period.start_date)
    overlap_end = min(base_period.end_date, period.end_date)
    if overlap_end < overlap_start:
        return 0

    base_days = (base_period.end_date - base_period.start_date).days + 1
    period_days = (overlap_end - overlap_start).days + 1
    return max(1, round(total_target_seconds * period_days / base_days))


def _build_goal_messages(
    *,
    user_text: str,
    timezone: str,
    today: date,
    previous_error: str | None,
    previous_data: dict[str, Any] | None,
) -> list[dict[str, str]]:
    messages = [
        {
            "role": "system",
            "content": (
                "You extract English speaking-practice goals from Russian or English user text. "
                "Return only JSON that matches the supplied schema. "
                "Use goal_type=periodic for goals like '10 hours per week' or '20 hours a month'. "
                "Use goal_type=total for goals like '100 hours in 6 months' or '50 hours by September'. "
                "For periodic goals, set period to week or month and deadline_date to an empty string. "
                "For total goals, set period to none and deadline_date to an ISO date. "
                "Resolve relative dates using the provided current date. "
                "If the user says 'за 6 месяцев', add six calendar months to the current date. "
                "Write assumptions in short Russian."
            ),
        },
        {
            "role": "user",
            "content": f"Timezone: {timezone}\nCurrent date: {today.isoformat()}\nGoal request: {user_text}",
        },
    ]
    if previous_error is not None:
        retry_lines = [
            "Previous structured-output attempt failed local validation.",
            f"Validation error: {previous_error}",
            "Try again for the same goal request. Return a corrected JSON object.",
        ]
        if previous_data is not None:
            retry_lines.extend(["Previous invalid JSON:", _compact_json_for_prompt(previous_data)])
        messages.append({"role": "user", "content": "\n".join(retry_lines)})
    return messages


def _compact_json_for_prompt(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)[:2000]

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from english_voice_bot.repositories import get_or_create_session, upsert_practice_goal
from english_voice_bot.services.activity import record_practice_activity
from english_voice_bot.services.goals import (
    GOAL_TYPE_PERIODIC,
    PERIOD_WEEK,
    format_goal_status_for_user,
    goal_to_json,
    parse_practice_goal_request,
    target_seconds_for_period,
    GoalPeriod,
    ParsedPracticeGoal,
)
from english_voice_bot.services.openrouter import OpenRouterError


class FakeGoalOpenRouter:
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


async def test_parse_practice_goal_request_retries_invalid_json() -> None:
    client = FakeGoalOpenRouter(
        [
            {
                "goal_type": "periodic",
                "target_hours": 10,
                "period": "none",
                "deadline_date": "",
                "assumptions": [],
            },
            {
                "goal_type": "periodic",
                "target_hours": 10,
                "period": "week",
                "deadline_date": "",
                "assumptions": [],
            },
        ]
    )

    goal = await parse_practice_goal_request(
        client,  # type: ignore[arg-type]
        user_text="хочу 10 часов в неделю",
        timezone="UTC",
        now=datetime(2026, 6, 22, 12, 0, tzinfo=UTC),
    )

    assert goal.goal_type == GOAL_TYPE_PERIODIC
    assert goal.target_minutes == 600
    assert goal.period == PERIOD_WEEK
    assert len(client.messages_by_call) == 2
    assert "Previous structured-output attempt failed" in client.messages_by_call[1][-1]["content"]


async def test_parse_practice_goal_request_raises_after_max_attempts() -> None:
    client = FakeGoalOpenRouter(
        [
            {"goal_type": "periodic", "target_hours": 10, "period": "none", "deadline_date": "", "assumptions": []},
            {"goal_type": "periodic", "target_hours": 10, "period": "none", "deadline_date": "", "assumptions": []},
            {"goal_type": "periodic", "target_hours": 10, "period": "none", "deadline_date": "", "assumptions": []},
        ]
    )

    with pytest.raises(OpenRouterError, match="after 3 attempts"):
        await parse_practice_goal_request(
            client,  # type: ignore[arg-type]
            user_text="10 часов",
            timezone="UTC",
            now=datetime(2026, 6, 22, 12, 0, tzinfo=UTC),
        )


async def test_format_goal_status_uses_current_week_stats(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    parsed_goal = ParsedPracticeGoal(
        goal_type=GOAL_TYPE_PERIODIC,
        target_minutes=60,
        period=PERIOD_WEEK,
        start_date=date(2026, 6, 22),
        deadline_date=None,
        assumptions=(),
    )
    async with session_factory() as db:
        session = await get_or_create_session(db, telegram_chat_id=1, telegram_user_id=2)
        await record_practice_activity(
            db,
            session_id=session.id,
            source_type="text",
            content="hello",
            timezone="UTC",
            occurred_at=datetime(2026, 6, 22, 9, 0, tzinfo=UTC),
        )
        await record_practice_activity(
            db,
            session_id=session.id,
            source_type="text",
            content="hello",
            timezone="UTC",
            occurred_at=datetime(2026, 6, 22, 9, 30, tzinfo=UTC),
        )
        await record_practice_activity(
            db,
            session_id=session.id,
            source_type="text",
            content="hello",
            timezone="UTC",
            occurred_at=datetime(2026, 6, 22, 9, 45, tzinfo=UTC),
        )
        goal = await upsert_practice_goal(
            db,
            telegram_chat_id=1,
            telegram_user_id=2,
            goal_type=parsed_goal.goal_type,
            target_minutes=parsed_goal.target_minutes,
            period=parsed_goal.period,
            start_date=parsed_goal.start_date,
            deadline_date=parsed_goal.deadline_date,
            goal_json=goal_to_json(parsed_goal),
        )

        report = await format_goal_status_for_user(
            db,
            telegram_chat_id=1,
            telegram_user_id=2,
            goal=goal,
            now=datetime(2026, 6, 22, 10, 0, tzinfo=UTC),
            timezone="UTC",
        )

    assert "Факт: 15 мин" in report
    assert "Цель: 1 ч" in report


def test_target_seconds_for_partial_period() -> None:
    assert (
        target_seconds_for_period(
            total_target_seconds=7 * 60 * 60,
            base_period=GoalPeriod(date(2026, 6, 22), date(2026, 6, 28), "week"),
            period=GoalPeriod(date(2026, 6, 22), date(2026, 6, 22), "day"),
        )
        == 60 * 60
    )

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from english_voice_bot.models import PracticeDailyStat
from english_voice_bot.repositories import (
    add_practice_activity_event,
    list_practice_activity_events,
    list_practice_daily_stats,
    replace_practice_daily_stats,
)

SESSION_GAP = timedelta(minutes=15)
WORD_RE = re.compile(r"[\w']+", re.UNICODE)


@dataclass(frozen=True)
class PracticeTotals:
    seconds: int
    messages: int
    words: int


def count_words(text: str) -> int:
    return len(WORD_RE.findall(text))


async def record_practice_activity(
    db: AsyncSession,
    *,
    session_id: int,
    source_type: str,
    content: str,
    timezone: str,
    telegram_message_id: int | None = None,
    occurred_at: datetime | None = None,
) -> None:
    await add_practice_activity_event(
        db,
        session_id=session_id,
        telegram_message_id=telegram_message_id,
        source_type=source_type,
        word_count=count_words(content),
        occurred_at=occurred_at,
    )
    await rebuild_practice_daily_stats(db, session_id=session_id, timezone=timezone)


async def rebuild_practice_daily_stats(
    db: AsyncSession,
    *,
    session_id: int,
    timezone: str,
) -> None:
    zone = ZoneInfo(timezone)
    events = await list_practice_activity_events(db, session_id=session_id)
    daily: dict[date, dict[str, int]] = defaultdict(lambda: {"messages": 0, "words": 0, "seconds": 0})

    previous_at: datetime | None = None
    for event in events:
        occurred_at = ensure_aware_utc(event.occurred_at)
        local_date = occurred_at.astimezone(zone).date()
        daily[local_date]["messages"] += 1
        daily[local_date]["words"] += event.word_count

        if previous_at is not None:
            gap = occurred_at - previous_at
            if timedelta(0) < gap <= SESSION_GAP:
                previous_local_date = previous_at.astimezone(zone).date()
                daily[previous_local_date]["seconds"] += int(gap.total_seconds())
        previous_at = occurred_at

    rows = [
        (local_date, values["messages"], values["words"], values["seconds"])
        for local_date, values in sorted(daily.items())
    ]
    await replace_practice_daily_stats(db, session_id=session_id, rows=rows)


async def get_practice_totals(
    db: AsyncSession,
    *,
    session_id: int,
    start_date: date,
    end_date: date,
) -> PracticeTotals:
    rows = await list_practice_daily_stats(
        db,
        session_id=session_id,
        start_date=start_date,
        end_date=end_date,
    )
    return totals_from_stats(rows)


async def format_results_report(
    db: AsyncSession,
    *,
    session_id: int,
    now: datetime,
    timezone: str,
) -> str:
    local_now = ensure_aware_utc(now).astimezone(ZoneInfo(timezone))
    month_start = local_now.date().replace(day=1)
    month_end = next_month_start(month_start) - timedelta(days=1)
    rows = await list_practice_daily_stats(
        db,
        session_id=session_id,
        start_date=month_start,
        end_date=month_end,
    )
    if not rows:
        return "📊 Пока нет сохранённой статистики за текущий месяц. Отправь пару сообщений, и я начну считать практику."

    lines = [f"📊 Результаты за {month_start:%B %Y}", "", "По дням:"]
    for row in rows:
        lines.append(
            f"{row.local_date:%Y-%m-%d}: {format_duration(row.practice_seconds)}"
            f" · {row.message_count} msg · {row.word_count} words"
        )

    lines.extend(["", "По неделям:"])
    for week_start, week_rows in group_stats_by_week(rows).items():
        week_end = min(week_start + timedelta(days=6), month_end)
        totals = totals_from_stats(week_rows)
        lines.append(f"{week_start:%d.%m}-{week_end:%d.%m}: {format_duration(totals.seconds)}")

    month_totals = totals_from_stats(rows)
    lines.extend(
        [
            "",
            f"Итого за месяц: {format_duration(month_totals.seconds)}",
            f"Сообщений: {month_totals.messages}",
            f"Слов: {month_totals.words}",
        ]
    )
    return "\n".join(lines)


def group_stats_by_week(rows: list[PracticeDailyStat]) -> dict[date, list[PracticeDailyStat]]:
    grouped: dict[date, list[PracticeDailyStat]] = {}
    for row in rows:
        week_start = row.local_date - timedelta(days=row.local_date.weekday())
        grouped.setdefault(week_start, []).append(row)
    return grouped


def totals_from_stats(rows: list[PracticeDailyStat]) -> PracticeTotals:
    return PracticeTotals(
        seconds=sum(row.practice_seconds for row in rows),
        messages=sum(row.message_count for row in rows),
        words=sum(row.word_count for row in rows),
    )


def next_month_start(value: date) -> date:
    if value.month == 12:
        return value.replace(year=value.year + 1, month=1, day=1)
    return value.replace(month=value.month + 1, day=1)


def format_duration(seconds: int) -> str:
    minutes = max(0, round(seconds / 60))
    hours, remainder = divmod(minutes, 60)
    if hours and remainder:
        return f"{hours} ч {remainder} мин"
    if hours:
        return f"{hours} ч"
    return f"{remainder} мин"


def ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)

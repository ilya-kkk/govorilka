from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from english_vocab_bot.config import VocabularySettings


def local_now(settings: VocabularySettings, now: datetime | None = None) -> datetime:
    if now is None:
        now = datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now.astimezone(ZoneInfo(settings.vocab_timezone))


def local_today(settings: VocabularySettings, now: datetime | None = None) -> date:
    return local_now(settings, now).date()

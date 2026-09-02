from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class VocabUser(Base):
    __tablename__ = "vocab_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    days: Mapped[list[VocabDay]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("telegram_chat_id", "telegram_user_id", name="uq_vocab_users_chat_user"),
        Index("ix_vocab_users_chat_user", "telegram_chat_id", "telegram_user_id"),
    )


class VocabDay(Base):
    __tablename__ = "vocab_days"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("vocab_users.id", ondelete="CASCADE"), nullable=False)
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    summary_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    user: Mapped[VocabUser] = relationship(back_populates="days")
    entries: Mapped[list[VocabEntry]] = relationship(
        back_populates="day",
        cascade="all, delete-orphan",
        order_by="VocabEntry.id",
    )

    __table_args__ = (
        UniqueConstraint("user_id", "local_date", name="uq_vocab_days_user_date"),
        Index("ix_vocab_days_user_date", "user_id", "local_date"),
    )


class VocabEntry(Base):
    __tablename__ = "vocab_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day_id: Mapped[int] = mapped_column(ForeignKey("vocab_days.id", ondelete="CASCADE"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    day: Mapped[VocabDay] = relationship(back_populates="entries")

    __table_args__ = (
        UniqueConstraint("day_id", "normalized_text", name="uq_vocab_entries_day_normalized_text"),
        Index("ix_vocab_entries_day_id_id", "day_id", "id"),
    )

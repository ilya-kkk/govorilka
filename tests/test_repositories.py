from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from english_voice_bot.models import DialogueMessage
from english_voice_bot.repositories import (
    ROLE_ASSISTANT,
    ROLE_USER,
    SOURCE_GENERATED,
    SOURCE_TEXT,
    add_dialogue_message,
    clear_session_dialogue,
    count_session_messages,
    get_or_create_session,
    get_recent_conversation_context,
    get_unreviewed_user_messages,
    mark_messages_reviewed,
)


async def test_add_messages_and_recent_history_is_chronological(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        session = await get_or_create_session(db, telegram_chat_id=10, telegram_user_id=20)
        await add_dialogue_message(
            db,
            session_id=session.id,
            role=ROLE_USER,
            source_type=SOURCE_TEXT,
            content="first",
        )
        await add_dialogue_message(
            db,
            session_id=session.id,
            role=ROLE_ASSISTANT,
            source_type=SOURCE_GENERATED,
            content="second",
        )
        await add_dialogue_message(
            db,
            session_id=session.id,
            role=ROLE_USER,
            source_type=SOURCE_TEXT,
            content="third",
        )

        recent = await get_recent_conversation_context(db, session_id=session.id, limit=2)

    assert [message.content for message in recent] == ["second", "third"]


async def test_selects_only_unreviewed_user_messages(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        session = await get_or_create_session(db, telegram_chat_id=1, telegram_user_id=2)
        first = await add_dialogue_message(
            db,
            session_id=session.id,
            role=ROLE_USER,
            source_type=SOURCE_TEXT,
            content="review me",
        )
        await add_dialogue_message(
            db,
            session_id=session.id,
            role=ROLE_ASSISTANT,
            source_type=SOURCE_GENERATED,
            content="assistant stays out",
        )
        second = await add_dialogue_message(
            db,
            session_id=session.id,
            role=ROLE_USER,
            source_type=SOURCE_TEXT,
            content="already reviewed",
        )
        await mark_messages_reviewed(db, session_id=session.id, message_ids=[second.id])

        unreviewed = await get_unreviewed_user_messages(db, session_id=session.id, limit=10)

    assert [message.id for message in unreviewed] == [first.id]


async def test_marks_only_selected_user_messages_reviewed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        session = await get_or_create_session(db, telegram_chat_id=1, telegram_user_id=2)
        selected = await add_dialogue_message(
            db,
            session_id=session.id,
            role=ROLE_USER,
            source_type=SOURCE_TEXT,
            content="selected",
        )
        untouched = await add_dialogue_message(
            db,
            session_id=session.id,
            role=ROLE_USER,
            source_type=SOURCE_TEXT,
            content="untouched",
        )
        assistant = await add_dialogue_message(
            db,
            session_id=session.id,
            role=ROLE_ASSISTANT,
            source_type=SOURCE_GENERATED,
            content="assistant",
        )

        count = await mark_messages_reviewed(
            db,
            session_id=session.id,
            message_ids=[selected.id, assistant.id],
        )
        rows = (
            await db.execute(
                select(DialogueMessage).where(DialogueMessage.id.in_([selected.id, untouched.id, assistant.id]))
            )
        ).scalars().all()
        by_id = {row.id: row for row in rows}

    assert count == 1
    assert by_id[selected.id].reviewed_at is not None
    assert by_id[untouched.id].reviewed_at is None
    assert by_id[assistant.id].reviewed_at is None


async def test_clear_session_deletes_dialogue(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        session = await get_or_create_session(db, telegram_chat_id=1, telegram_user_id=2)
        await add_dialogue_message(
            db,
            session_id=session.id,
            role=ROLE_USER,
            source_type=SOURCE_TEXT,
            content="hello",
        )
        deleted = await clear_session_dialogue(db, session_id=session.id)
        remaining = await count_session_messages(db, session_id=session.id)

    assert deleted == 1
    assert remaining == 0

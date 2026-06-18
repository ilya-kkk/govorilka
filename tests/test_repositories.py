from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from english_voice_bot.models import DialogueMessage
from english_voice_bot.repositories import (
    PENDING_ACTION_REMINDER_SETUP,
    ROLE_ASSISTANT,
    ROLE_USER,
    SOURCE_GENERATED,
    SOURCE_TEXT,
    add_dialogue_message,
    clear_pending_user_action,
    clear_reminder_schedule_draft,
    clear_session_dialogue,
    count_session_messages,
    get_pending_user_action,
    get_reminder_schedule_draft,
    get_reminder_schedule,
    get_or_create_session,
    get_recent_conversation_context,
    get_unreviewed_user_messages,
    list_enabled_reminder_schedules,
    mark_messages_reviewed,
    set_pending_user_action,
    upsert_reminder_schedule_draft,
    update_reminder_last_sent_slot,
    upsert_reminder_schedule,
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


async def test_pending_user_action_round_trip(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        await set_pending_user_action(
            db,
            telegram_chat_id=10,
            telegram_user_id=20,
            action=PENDING_ACTION_REMINDER_SETUP,
        )
        pending = await get_pending_user_action(db, telegram_chat_id=10, telegram_user_id=20)
        deleted = await clear_pending_user_action(
            db,
            telegram_chat_id=10,
            telegram_user_id=20,
            action=PENDING_ACTION_REMINDER_SETUP,
        )
        missing = await get_pending_user_action(db, telegram_chat_id=10, telegram_user_id=20)

    assert pending is not None
    assert pending.action == PENDING_ACTION_REMINDER_SETUP
    assert deleted == 1
    assert missing is None


async def test_reminder_schedule_upsert_and_last_sent_slot(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        created = await upsert_reminder_schedule(
            db,
            telegram_chat_id=10,
            telegram_user_id=20,
            timezone="UTC",
            schedule_json='{"days":[]}',
        )
        await upsert_reminder_schedule(
            db,
            telegram_chat_id=10,
            telegram_user_id=20,
            timezone="UTC",
            schedule_json='{"days":[1]}',
        )
        await update_reminder_last_sent_slot(db, schedule_id=created.id, last_sent_slot="2026-06-18:09:00")
        found = await get_reminder_schedule(db, telegram_chat_id=10, telegram_user_id=20)
        enabled = await list_enabled_reminder_schedules(db)

    assert found is not None
    assert found.id == created.id
    assert found.schedule_json == '{"days":[1]}'
    assert found.last_sent_slot == "2026-06-18:09:00"
    assert [schedule.id for schedule in enabled] == [created.id]


async def test_reminder_schedule_draft_round_trip(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        created = await upsert_reminder_schedule_draft(
            db,
            telegram_chat_id=10,
            telegram_user_id=20,
            timezone="Europe/Moscow",
            schedule_json='{"draft":1}',
        )
        updated = await upsert_reminder_schedule_draft(
            db,
            telegram_chat_id=10,
            telegram_user_id=20,
            timezone="Europe/Moscow",
            schedule_json='{"draft":2}',
        )
        found = await get_reminder_schedule_draft(db, telegram_chat_id=10, telegram_user_id=20)
        deleted = await clear_reminder_schedule_draft(db, telegram_chat_id=10, telegram_user_id=20)
        missing = await get_reminder_schedule_draft(db, telegram_chat_id=10, telegram_user_id=20)

    assert updated.id == created.id
    assert found is not None
    assert found.schedule_json == '{"draft":2}'
    assert deleted == 1
    assert missing is None

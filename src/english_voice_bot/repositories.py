from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from english_voice_bot.models import (
    ChatSession,
    DialogueMessage,
    GoalReminderSchedule,
    GoalReminderScheduleDraft,
    PendingUserAction,
    PracticeActivityEvent,
    PracticeDailyStat,
    PracticeGoal,
    PracticeQuestion,
    ReminderSchedule,
    ReminderScheduleDraft,
    utc_now,
)

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"

SOURCE_VOICE = "voice"
SOURCE_TEXT = "text"
SOURCE_GENERATED = "generated"

PENDING_ACTION_REMINDER_SETUP = "reminder_setup"
PENDING_ACTION_GOAL_SETUP = "goal_setup"
PENDING_ACTION_GOAL_REMINDER_SETUP = "goal_reminder_setup"


async def get_or_create_session(
    db: AsyncSession,
    *,
    telegram_chat_id: int,
    telegram_user_id: int,
) -> ChatSession:
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.telegram_chat_id == telegram_chat_id,
            ChatSession.telegram_user_id == telegram_user_id,
        )
    )
    session = result.scalar_one_or_none()
    if session is not None:
        session.updated_at = utc_now()
        await db.flush()
        return session

    session = ChatSession(
        telegram_chat_id=telegram_chat_id,
        telegram_user_id=telegram_user_id,
    )
    db.add(session)
    await db.flush()
    return session


async def add_dialogue_message(
    db: AsyncSession,
    *,
    session_id: int,
    role: str,
    source_type: str,
    content: str,
    telegram_message_id: int | None = None,
) -> DialogueMessage:
    message = DialogueMessage(
        session_id=session_id,
        telegram_message_id=telegram_message_id,
        role=role,
        source_type=source_type,
        content=content,
    )
    db.add(message)
    await db.flush()
    return message


async def get_recent_conversation_context(
    db: AsyncSession,
    *,
    session_id: int,
    limit: int,
) -> list[DialogueMessage]:
    result = await db.execute(
        select(DialogueMessage)
        .where(DialogueMessage.session_id == session_id)
        .order_by(DialogueMessage.id.desc())
        .limit(limit)
    )
    return list(reversed(result.scalars().all()))


async def get_unreviewed_user_messages(
    db: AsyncSession,
    *,
    session_id: int,
    limit: int,
) -> list[DialogueMessage]:
    result = await db.execute(
        select(DialogueMessage)
        .where(
            DialogueMessage.session_id == session_id,
            DialogueMessage.role == ROLE_USER,
            DialogueMessage.reviewed_at.is_(None),
        )
        .order_by(DialogueMessage.id.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_context_around_selected_messages(
    db: AsyncSession,
    *,
    session_id: int,
    selected_message_ids: Sequence[int],
    window_size: int = 3,
) -> list[DialogueMessage]:
    if not selected_message_ids:
        return []

    result = await db.execute(
        select(DialogueMessage)
        .where(DialogueMessage.session_id == session_id)
        .order_by(DialogueMessage.id.asc())
    )
    all_messages = list(result.scalars().all())
    selected_ids = set(selected_message_ids)
    selected_indexes = [index for index, message in enumerate(all_messages) if message.id in selected_ids]
    if not selected_indexes:
        return []

    keep_indexes: set[int] = set()
    for index in selected_indexes:
        start = max(0, index - window_size)
        end = min(len(all_messages), index + window_size + 1)
        keep_indexes.update(range(start, end))

    return [message for index, message in enumerate(all_messages) if index in keep_indexes]


async def mark_messages_reviewed(
    db: AsyncSession,
    *,
    session_id: int,
    message_ids: Sequence[int],
) -> int:
    if not message_ids:
        return 0
    result = await db.execute(
        update(DialogueMessage)
        .where(
            DialogueMessage.session_id == session_id,
            DialogueMessage.role == ROLE_USER,
            DialogueMessage.id.in_(message_ids),
        )
        .values(reviewed_at=utc_now())
    )
    await db.flush()
    return int(result.rowcount or 0)


async def clear_session_dialogue(db: AsyncSession, *, session_id: int) -> int:
    result = await db.execute(delete(DialogueMessage).where(DialogueMessage.session_id == session_id))
    await db.flush()
    return int(result.rowcount or 0)


async def count_session_messages(db: AsyncSession, *, session_id: int) -> int:
    result = await db.execute(
        select(func.count(DialogueMessage.id)).where(DialogueMessage.session_id == session_id)
    )
    return int(result.scalar_one())


async def add_practice_activity_event(
    db: AsyncSession,
    *,
    session_id: int,
    source_type: str,
    word_count: int,
    telegram_message_id: int | None = None,
    occurred_at: datetime | None = None,
) -> PracticeActivityEvent:
    event = PracticeActivityEvent(
        session_id=session_id,
        telegram_message_id=telegram_message_id,
        source_type=source_type,
        word_count=word_count,
        occurred_at=occurred_at or utc_now(),
    )
    db.add(event)
    await db.flush()
    return event


async def list_practice_activity_events(
    db: AsyncSession,
    *,
    session_id: int,
) -> list[PracticeActivityEvent]:
    result = await db.execute(
        select(PracticeActivityEvent)
        .where(PracticeActivityEvent.session_id == session_id)
        .order_by(PracticeActivityEvent.occurred_at.asc(), PracticeActivityEvent.id.asc())
    )
    return list(result.scalars().all())


async def replace_practice_daily_stats(
    db: AsyncSession,
    *,
    session_id: int,
    rows: Sequence[tuple[date, int, int, int]],
) -> None:
    await db.execute(delete(PracticeDailyStat).where(PracticeDailyStat.session_id == session_id))
    for local_date, message_count, word_count, practice_seconds in rows:
        db.add(
            PracticeDailyStat(
                session_id=session_id,
                local_date=local_date,
                message_count=message_count,
                word_count=word_count,
                practice_seconds=practice_seconds,
            )
        )
    await db.flush()


async def list_practice_daily_stats(
    db: AsyncSession,
    *,
    session_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[PracticeDailyStat]:
    query = select(PracticeDailyStat).where(PracticeDailyStat.session_id == session_id)
    if start_date is not None:
        query = query.where(PracticeDailyStat.local_date >= start_date)
    if end_date is not None:
        query = query.where(PracticeDailyStat.local_date <= end_date)
    result = await db.execute(query.order_by(PracticeDailyStat.local_date.asc()))
    return list(result.scalars().all())


async def set_pending_user_action(
    db: AsyncSession,
    *,
    telegram_chat_id: int,
    telegram_user_id: int,
    action: str,
) -> PendingUserAction:
    result = await db.execute(
        select(PendingUserAction).where(
            PendingUserAction.telegram_chat_id == telegram_chat_id,
            PendingUserAction.telegram_user_id == telegram_user_id,
        )
    )
    pending = result.scalar_one_or_none()
    if pending is not None:
        pending.action = action
        pending.updated_at = utc_now()
        await db.flush()
        return pending

    pending = PendingUserAction(
        telegram_chat_id=telegram_chat_id,
        telegram_user_id=telegram_user_id,
        action=action,
    )
    db.add(pending)
    await db.flush()
    return pending


async def get_pending_user_action(
    db: AsyncSession,
    *,
    telegram_chat_id: int,
    telegram_user_id: int,
) -> PendingUserAction | None:
    result = await db.execute(
        select(PendingUserAction).where(
            PendingUserAction.telegram_chat_id == telegram_chat_id,
            PendingUserAction.telegram_user_id == telegram_user_id,
        )
    )
    return result.scalar_one_or_none()


async def clear_pending_user_action(
    db: AsyncSession,
    *,
    telegram_chat_id: int,
    telegram_user_id: int,
    action: str | None = None,
) -> int:
    query = delete(PendingUserAction).where(
        PendingUserAction.telegram_chat_id == telegram_chat_id,
        PendingUserAction.telegram_user_id == telegram_user_id,
    )
    if action is not None:
        query = query.where(PendingUserAction.action == action)
    result = await db.execute(query)
    await db.flush()
    return int(result.rowcount or 0)


async def upsert_reminder_schedule(
    db: AsyncSession,
    *,
    telegram_chat_id: int,
    telegram_user_id: int,
    timezone: str,
    schedule_json: str,
    enabled: bool = True,
) -> ReminderSchedule:
    result = await db.execute(
        select(ReminderSchedule).where(
            ReminderSchedule.telegram_chat_id == telegram_chat_id,
            ReminderSchedule.telegram_user_id == telegram_user_id,
        )
    )
    schedule = result.scalar_one_or_none()
    if schedule is not None:
        schedule.enabled = enabled
        schedule.timezone = timezone
        schedule.schedule_json = schedule_json
        schedule.last_sent_slot = None
        schedule.updated_at = utc_now()
        await db.flush()
        return schedule

    schedule = ReminderSchedule(
        telegram_chat_id=telegram_chat_id,
        telegram_user_id=telegram_user_id,
        enabled=enabled,
        timezone=timezone,
        schedule_json=schedule_json,
    )
    db.add(schedule)
    await db.flush()
    return schedule


async def upsert_reminder_schedule_draft(
    db: AsyncSession,
    *,
    telegram_chat_id: int,
    telegram_user_id: int,
    timezone: str,
    schedule_json: str,
) -> ReminderScheduleDraft:
    result = await db.execute(
        select(ReminderScheduleDraft).where(
            ReminderScheduleDraft.telegram_chat_id == telegram_chat_id,
            ReminderScheduleDraft.telegram_user_id == telegram_user_id,
        )
    )
    draft = result.scalar_one_or_none()
    if draft is not None:
        draft.timezone = timezone
        draft.schedule_json = schedule_json
        draft.updated_at = utc_now()
        await db.flush()
        return draft

    draft = ReminderScheduleDraft(
        telegram_chat_id=telegram_chat_id,
        telegram_user_id=telegram_user_id,
        timezone=timezone,
        schedule_json=schedule_json,
    )
    db.add(draft)
    await db.flush()
    return draft


async def get_reminder_schedule_draft(
    db: AsyncSession,
    *,
    telegram_chat_id: int,
    telegram_user_id: int,
) -> ReminderScheduleDraft | None:
    result = await db.execute(
        select(ReminderScheduleDraft).where(
            ReminderScheduleDraft.telegram_chat_id == telegram_chat_id,
            ReminderScheduleDraft.telegram_user_id == telegram_user_id,
        )
    )
    return result.scalar_one_or_none()


async def clear_reminder_schedule_draft(
    db: AsyncSession,
    *,
    telegram_chat_id: int,
    telegram_user_id: int,
) -> int:
    result = await db.execute(
        delete(ReminderScheduleDraft).where(
            ReminderScheduleDraft.telegram_chat_id == telegram_chat_id,
            ReminderScheduleDraft.telegram_user_id == telegram_user_id,
        )
    )
    await db.flush()
    return int(result.rowcount or 0)


async def get_reminder_schedule(
    db: AsyncSession,
    *,
    telegram_chat_id: int,
    telegram_user_id: int,
) -> ReminderSchedule | None:
    result = await db.execute(
        select(ReminderSchedule).where(
            ReminderSchedule.telegram_chat_id == telegram_chat_id,
            ReminderSchedule.telegram_user_id == telegram_user_id,
        )
    )
    return result.scalar_one_or_none()


async def list_enabled_reminder_schedules(db: AsyncSession) -> list[ReminderSchedule]:
    result = await db.execute(select(ReminderSchedule).where(ReminderSchedule.enabled.is_(True)))
    return list(result.scalars().all())


async def update_reminder_last_sent_slot(
    db: AsyncSession,
    *,
    schedule_id: int,
    last_sent_slot: str,
) -> int:
    result = await db.execute(
        update(ReminderSchedule)
        .where(ReminderSchedule.id == schedule_id)
        .values(last_sent_slot=last_sent_slot, updated_at=utc_now())
    )
    await db.flush()
    return int(result.rowcount or 0)


async def upsert_practice_questions(
    db: AsyncSession,
    *,
    questions: Sequence[tuple[str, str, str | None]],
) -> int:
    inserted_count = 0
    for source_key, text, topic in questions:
        result = await db.execute(select(PracticeQuestion).where(PracticeQuestion.source_key == source_key))
        question = result.scalar_one_or_none()
        if question is not None:
            if question.text != text or question.topic != topic:
                question.text = text
                question.topic = topic
                question.updated_at = utc_now()
            continue

        db.add(PracticeQuestion(source_key=source_key, text=text, topic=topic))
        inserted_count += 1
    await db.flush()
    return inserted_count


async def sync_practice_questions(
    db: AsyncSession,
    *,
    questions: Sequence[tuple[str, str, str | None]],
) -> int:
    if not questions:
        return 0

    inserted_count = await upsert_practice_questions(db, questions=questions)
    source_keys = [source_key for source_key, _text, _topic in questions]
    await db.execute(delete(PracticeQuestion).where(~PracticeQuestion.source_key.in_(source_keys)))
    await db.flush()
    return inserted_count


async def count_practice_questions(db: AsyncSession) -> int:
    result = await db.execute(select(func.count(PracticeQuestion.id)))
    return int(result.scalar_one())


async def get_next_practice_question(db: AsyncSession) -> PracticeQuestion | None:
    result = await db.execute(
        select(PracticeQuestion).order_by(
            PracticeQuestion.asked_count.asc(),
            PracticeQuestion.last_asked_at.is_not(None).asc(),
            PracticeQuestion.last_asked_at.asc(),
            PracticeQuestion.id.asc(),
        )
    )
    return result.scalars().first()


async def mark_practice_question_asked(
    db: AsyncSession,
    *,
    question_id: int,
) -> int:
    result = await db.execute(
        update(PracticeQuestion)
        .where(PracticeQuestion.id == question_id)
        .values(
            asked_count=PracticeQuestion.asked_count + 1,
            last_asked_at=utc_now(),
            updated_at=utc_now(),
        )
    )
    await db.flush()
    return int(result.rowcount or 0)


async def upsert_practice_goal(
    db: AsyncSession,
    *,
    telegram_chat_id: int,
    telegram_user_id: int,
    goal_type: str,
    target_minutes: int,
    period: str,
    start_date: date,
    deadline_date: date | None,
    goal_json: str,
    enabled: bool = True,
) -> PracticeGoal:
    result = await db.execute(
        select(PracticeGoal).where(
            PracticeGoal.telegram_chat_id == telegram_chat_id,
            PracticeGoal.telegram_user_id == telegram_user_id,
        )
    )
    goal = result.scalar_one_or_none()
    if goal is not None:
        goal.enabled = enabled
        goal.goal_type = goal_type
        goal.target_minutes = target_minutes
        goal.period = period
        goal.start_date = start_date
        goal.deadline_date = deadline_date
        goal.goal_json = goal_json
        goal.updated_at = utc_now()
        await db.flush()
        return goal

    goal = PracticeGoal(
        telegram_chat_id=telegram_chat_id,
        telegram_user_id=telegram_user_id,
        enabled=enabled,
        goal_type=goal_type,
        target_minutes=target_minutes,
        period=period,
        start_date=start_date,
        deadline_date=deadline_date,
        goal_json=goal_json,
    )
    db.add(goal)
    await db.flush()
    return goal


async def get_practice_goal(
    db: AsyncSession,
    *,
    telegram_chat_id: int,
    telegram_user_id: int,
) -> PracticeGoal | None:
    result = await db.execute(
        select(PracticeGoal).where(
            PracticeGoal.telegram_chat_id == telegram_chat_id,
            PracticeGoal.telegram_user_id == telegram_user_id,
            PracticeGoal.enabled.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def upsert_goal_reminder_schedule(
    db: AsyncSession,
    *,
    telegram_chat_id: int,
    telegram_user_id: int,
    timezone: str,
    schedule_json: str,
    enabled: bool = True,
) -> GoalReminderSchedule:
    result = await db.execute(
        select(GoalReminderSchedule).where(
            GoalReminderSchedule.telegram_chat_id == telegram_chat_id,
            GoalReminderSchedule.telegram_user_id == telegram_user_id,
        )
    )
    schedule = result.scalar_one_or_none()
    if schedule is not None:
        schedule.enabled = enabled
        schedule.timezone = timezone
        schedule.schedule_json = schedule_json
        schedule.last_sent_slot = None
        schedule.updated_at = utc_now()
        await db.flush()
        return schedule

    schedule = GoalReminderSchedule(
        telegram_chat_id=telegram_chat_id,
        telegram_user_id=telegram_user_id,
        enabled=enabled,
        timezone=timezone,
        schedule_json=schedule_json,
    )
    db.add(schedule)
    await db.flush()
    return schedule


async def upsert_goal_reminder_schedule_draft(
    db: AsyncSession,
    *,
    telegram_chat_id: int,
    telegram_user_id: int,
    timezone: str,
    schedule_json: str,
) -> GoalReminderScheduleDraft:
    result = await db.execute(
        select(GoalReminderScheduleDraft).where(
            GoalReminderScheduleDraft.telegram_chat_id == telegram_chat_id,
            GoalReminderScheduleDraft.telegram_user_id == telegram_user_id,
        )
    )
    draft = result.scalar_one_or_none()
    if draft is not None:
        draft.timezone = timezone
        draft.schedule_json = schedule_json
        draft.updated_at = utc_now()
        await db.flush()
        return draft

    draft = GoalReminderScheduleDraft(
        telegram_chat_id=telegram_chat_id,
        telegram_user_id=telegram_user_id,
        timezone=timezone,
        schedule_json=schedule_json,
    )
    db.add(draft)
    await db.flush()
    return draft


async def get_goal_reminder_schedule_draft(
    db: AsyncSession,
    *,
    telegram_chat_id: int,
    telegram_user_id: int,
) -> GoalReminderScheduleDraft | None:
    result = await db.execute(
        select(GoalReminderScheduleDraft).where(
            GoalReminderScheduleDraft.telegram_chat_id == telegram_chat_id,
            GoalReminderScheduleDraft.telegram_user_id == telegram_user_id,
        )
    )
    return result.scalar_one_or_none()


async def clear_goal_reminder_schedule_draft(
    db: AsyncSession,
    *,
    telegram_chat_id: int,
    telegram_user_id: int,
) -> int:
    result = await db.execute(
        delete(GoalReminderScheduleDraft).where(
            GoalReminderScheduleDraft.telegram_chat_id == telegram_chat_id,
            GoalReminderScheduleDraft.telegram_user_id == telegram_user_id,
        )
    )
    await db.flush()
    return int(result.rowcount or 0)


async def list_enabled_goal_reminder_schedules(db: AsyncSession) -> list[GoalReminderSchedule]:
    result = await db.execute(select(GoalReminderSchedule).where(GoalReminderSchedule.enabled.is_(True)))
    return list(result.scalars().all())


async def update_goal_reminder_last_sent_slot(
    db: AsyncSession,
    *,
    schedule_id: int,
    last_sent_slot: str,
) -> int:
    result = await db.execute(
        update(GoalReminderSchedule)
        .where(GoalReminderSchedule.id == schedule_id)
        .values(last_sent_slot=last_sent_slot, updated_at=utc_now())
    )
    await db.flush()
    return int(result.rowcount or 0)

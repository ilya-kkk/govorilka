from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, FSInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from english_vocab_bot.config import VocabularySettings
from english_vocab_bot.db import session_scope
from english_vocab_bot.formatting import apkg_filename
from english_vocab_bot.handlers.guards import reject_callback_if_not_allowed
from english_vocab_bot.keyboards import DOWNLOAD_CALLBACK_PREFIX, download_keyboard
from english_vocab_bot.repositories import get_day_for_user, list_day_entries, mark_day_downloaded
from english_vocab_bot.services.anki_export import TranslatorLike, export_words_to_apkg

logger = logging.getLogger(__name__)
router = Router()

BUILDING_FILE_TEXT = "Формирую файл..."
EMPTY_LIST_TEXT = "Список за этот день пока пустой."
EXPORT_ERROR_TEXT = "Не получилось собрать файл. Попробуй нажать кнопку еще раз чуть позже."


@router.callback_query(F.data.startswith(DOWNLOAD_CALLBACK_PREFIX))
async def download_callback(
    callback: CallbackQuery,
    settings: VocabularySettings,
    session_factory: async_sessionmaker[AsyncSession],
    translator: TranslatorLike,
) -> None:
    if await reject_callback_if_not_allowed(callback, settings):
        return
    if callback.from_user is None:
        return
    if callback.message is None or not isinstance(callback.message, Message):
        await callback.answer("Не вижу сообщение со словариком.", show_alert=True)
        return

    day_id = _parse_day_id(callback.data)
    if day_id is None:
        await callback.answer("Не понимаю, какой день скачать.", show_alert=True)
        return

    async with session_scope(session_factory) as db:
        day = await get_day_for_user(db, day_id=day_id, telegram_user_id=callback.from_user.id)
        if day is None:
            await callback.answer("Не нашел этот словарик.", show_alert=True)
            return
        entries = await list_day_entries(db, day_id=day.id)
        words = [entry.text for entry in entries]
        local_date = day.local_date

    if not words:
        await callback.answer(EMPTY_LIST_TEXT, show_alert=True)
        return

    await callback.answer(BUILDING_FILE_TEXT)
    await _safe_set_keyboard(callback.message, reply_markup=None)
    status = await callback.message.answer(BUILDING_FILE_TEXT)

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / apkg_filename(local_date)
            await export_words_to_apkg(
                words=words,
                translator=translator,
                output_path=output_path,
                deck_name=settings.vocab_deck_name,
            )
            await callback.message.answer_document(
                FSInputFile(output_path),
                caption=f"Готово: {len(words)} карточек.",
            )
    except Exception:
        logger.exception("Vocabulary APKG export failed", extra={"day_id": day_id})
        await _safe_edit_status(status, EXPORT_ERROR_TEXT)
        await _safe_set_keyboard(callback.message, reply_markup=download_keyboard(day_id))
        return

    async with session_scope(session_factory) as db:
        day = await get_day_for_user(db, day_id=day_id, telegram_user_id=callback.from_user.id)
        if day is not None:
            await mark_day_downloaded(db, day=day)
            await db.commit()

    await _safe_edit_status(status, f"Готово: {len(words)} карточек.")


def _parse_day_id(data: str | None) -> int | None:
    if not data or not data.startswith(DOWNLOAD_CALLBACK_PREFIX):
        return None
    raw_day_id = data.removeprefix(DOWNLOAD_CALLBACK_PREFIX)
    try:
        return int(raw_day_id)
    except ValueError:
        return None


async def _safe_set_keyboard(message: Message, *, reply_markup: object) -> None:
    try:
        await message.edit_reply_markup(reply_markup=reply_markup)
    except TelegramAPIError:
        logger.debug("Could not update vocabulary download keyboard", exc_info=True)


async def _safe_edit_status(status: Message, text: str) -> None:
    try:
        await status.edit_text(text)
    except TelegramAPIError:
        await status.answer(text)

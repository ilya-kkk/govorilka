from __future__ import annotations

from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Message

from english_vocab_bot.config import VocabularySettings


def is_allowed_user(user_id: int | None, settings: VocabularySettings) -> bool:
    if user_id is None:
        return False
    return not settings.allowed_telegram_user_ids or user_id in settings.allowed_telegram_user_ids


async def reject_message_if_not_allowed(message: Message, settings: VocabularySettings) -> bool:
    if message.chat.type != ChatType.PRIVATE:
        await message.answer("Открой, пожалуйста, личный чат со мной.")
        return True
    if not is_allowed_user(message.from_user.id if message.from_user else None, settings):
        await message.answer("Этот бот приватный.")
        return True
    return False


async def reject_callback_if_not_allowed(
    callback: CallbackQuery,
    settings: VocabularySettings,
) -> bool:
    if not is_allowed_user(callback.from_user.id if callback.from_user else None, settings):
        await callback.answer("Этот бот приватный.", show_alert=True)
        return True
    return False

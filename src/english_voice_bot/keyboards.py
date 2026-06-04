from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

REVIEW_BUTTON_TEXT = "🔍 Find my mistakes"
RESET_BUTTON_TEXT = "🧹 Reset dialogue"


def dialogue_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=REVIEW_BUTTON_TEXT)]],
        resize_keyboard=True,
        input_field_placeholder="Send a voice message in English",
    )


def dialogue_actions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=RESET_BUTTON_TEXT, callback_data="dialogue:reset")],
        ]
    )

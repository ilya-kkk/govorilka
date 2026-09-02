from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

DOWNLOAD_CALLBACK_PREFIX = "vocab:download:"
DOWNLOAD_BUTTON_TEXT = "Скачать .apkg"


def download_keyboard(day_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=DOWNLOAD_BUTTON_TEXT,
                    callback_data=f"{DOWNLOAD_CALLBACK_PREFIX}{day_id}",
                )
            ],
        ]
    )

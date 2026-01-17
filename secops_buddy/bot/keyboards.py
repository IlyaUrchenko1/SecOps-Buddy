from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="/status"), KeyboardButton(text="/diff")],
            [KeyboardButton(text="/report"), KeyboardButton(text="/endpoints")],
            [KeyboardButton(text="/help")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Команды: /start /status /diff /report /endpoints",
    )

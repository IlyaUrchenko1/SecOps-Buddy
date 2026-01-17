from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Статус"), KeyboardButton(text="🧾 Отчёт")],
            [KeyboardButton(text="🔀 Изменения"), KeyboardButton(text="🔌 Подключение")],
            [KeyboardButton(text="ℹ️ Помощь")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Нажми кнопку или введи команду: /status /report /diff /endpoints /help",
    )

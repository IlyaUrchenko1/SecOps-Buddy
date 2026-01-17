from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aiogram import Router
from aiogram import F
from aiogram.filters import Command
from aiogram.types import Message

from .keyboards import main_menu_kb


@dataclass(frozen=True, slots=True)
class BotContext:
    allowed_users: set[int]
    state_dir: Path
    root: Path
    config_path: Path


def _is_allowed(message: Message, allowed: set[int]) -> bool:
    uid = message.from_user.id if message.from_user else None
    return uid in allowed


def _access_denied_text(uid: int | None) -> str:
    s = ["<b>⛔ Доступ запрещён</b>", "", "Этот бот работает только для разрешённых пользователей."]
    if uid is not None:
        s.extend(["", f"Твой Telegram ID: <code>{uid}</code>"])
    return "\n".join(s)


def _help_text() -> str:
    return "\n".join(
        [
            "<b>Команды</b>",
            "",
            "<b>/status</b> — статус бота и сервера",
            "<b>/report</b> — snapshot + diff в одном сообщении",
            "<b>/diff</b> — изменения относительно прошлого snapshot",
            "<b>/endpoints</b> — IP/порты/протоколы из последнего snapshot",
            "<b>/help</b> — подсказка",
        ]
    )


def _start_text() -> str:
    return "\n".join(
        [
            "<b>SecOps Buddy</b>",
            "<i>мониторинг безопасности сервера</i>",
            "",
            "<b>Быстрые действия</b>",
            "",
            "<b>📊 Статус</b>",
            "<i>Состояние бота/сервера, ОЗУ, последние данные, входы</i>",
            "",
            "<b>🧾 Отчёт</b>",
            "<i>Snapshot + diff в одном сообщении</i>",
            "",
            "<b>🔀 Изменения</b>",
            "<i>Что поменялось с прошлого snapshot</i>",
            "",
            "<b>🔌 Подключение</b>",
            "<i>IP/порты/протоколы из последнего snapshot</i>",
            "",
            "<b>Если данных нет</b>",
            "Запусти agent, чтобы появился snapshot, и нажми «🧾 Отчёт».",
            "",
            _help_text(),
        ]
    )

def build_router(ctx: BotContext, read_status_text, read_endpoints_text, read_diff_text, read_report_text) -> Router:
    router = Router()

    def uid(message: Message) -> int | None:
        return message.from_user.id if message.from_user else None

    @router.message(Command("start"))
    async def cmd_start(message: Message) -> None:
        if not _is_allowed(message, ctx.allowed_users):
            await message.answer(_access_denied_text(uid(message)))
            return
        await message.answer(_start_text(), reply_markup=main_menu_kb())

    @router.message(Command("help"))
    async def cmd_help(message: Message) -> None:
        if not _is_allowed(message, ctx.allowed_users):
            await message.answer(_access_denied_text(uid(message)))
            return
        await message.answer(_help_text(), reply_markup=main_menu_kb())

    @router.message(Command("status"))
    async def cmd_status(message: Message) -> None:
        if not _is_allowed(message, ctx.allowed_users):
            await message.answer(_access_denied_text(uid(message)))
            return
        await message.answer(read_status_text(), reply_markup=main_menu_kb())

    @router.message(F.text == "📊 Статус")
    async def btn_status(message: Message) -> None:
        await cmd_status(message)

    @router.message(F.text == "Статус")
    async def btn_status_plain(message: Message) -> None:
        await cmd_status(message)

    @router.message(Command("endpoints"))
    async def cmd_endpoints(message: Message) -> None:
        if not _is_allowed(message, ctx.allowed_users):
            await message.answer(_access_denied_text(uid(message)))
            return
        await message.answer(read_endpoints_text(), reply_markup=main_menu_kb())

    @router.message(F.text == "🔌 Подключение")
    async def btn_endpoints(message: Message) -> None:
        await cmd_endpoints(message)

    @router.message(F.text == "Подключение")
    async def btn_endpoints_plain(message: Message) -> None:
        await cmd_endpoints(message)

    @router.message(Command("diff"))
    async def cmd_diff(message: Message) -> None:
        if not _is_allowed(message, ctx.allowed_users):
            await message.answer(_access_denied_text(uid(message)))
            return
        await message.answer(read_diff_text(), reply_markup=main_menu_kb())

    @router.message(F.text == "🔀 Изменения")
    async def btn_diff(message: Message) -> None:
        await cmd_diff(message)

    @router.message(F.text == "Изменения")
    async def btn_diff_plain(message: Message) -> None:
        await cmd_diff(message)

    @router.message(Command("report"))
    async def cmd_report(message: Message) -> None:
        if not _is_allowed(message, ctx.allowed_users):
            await message.answer(_access_denied_text(uid(message)))
            return
        await message.answer(read_report_text(), reply_markup=main_menu_kb())

    @router.message(F.text == "🧾 Отчёт")
    async def btn_report(message: Message) -> None:
        await cmd_report(message)

    @router.message((F.text == "Отчёт") | (F.text == "Отчет"))
    async def btn_report_plain(message: Message) -> None:
        await cmd_report(message)

    @router.message(F.text == "ℹ️ Помощь")
    async def btn_help(message: Message) -> None:
        await cmd_help(message)

    @router.message(F.text == "Помощь")
    async def btn_help_plain(message: Message) -> None:
        await cmd_help(message)

    return router

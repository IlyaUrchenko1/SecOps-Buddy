from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from .keyboards import main_menu_kb


@dataclass(frozen=True, slots=True)
class BotContext:
    allowed_users: set[int]
    state_dir: Path


def _is_allowed(message: Message, allowed: set[int]) -> bool:
    uid = message.from_user.id if message.from_user else None
    return uid in allowed


def _access_denied_text() -> str:
    return "<b>Доступ запрещён</b>\n\nЭтот бот работает только для разрешённых пользователей."


def _help_text() -> str:
    return "\n".join(
        [
            "<b>Команды</b>",
            "",
            "<b>/status</b> — краткий статус (последний snapshot)",
            "<b>/diff</b> — изменения относительно прошлого snapshot",
            "<b>/report</b> — статус + diff одним сообщением",
        ]
    )


def _start_text(snapshot_text: str) -> str:
    return "\n".join(
        [
            "<b>SecOps Buddy</b>",
            "",
            "Я показываю результаты последнего сканирования сервера.",
            "",
            snapshot_text,
            "",
            _help_text(),
        ]
    )


def build_router(ctx: BotContext, read_snapshot_text, read_diff_text, read_report_text) -> Router:
    router = Router()

    @router.message(Command("start"))
    async def cmd_start(message: Message) -> None:
        if not _is_allowed(message, ctx.allowed_users):
            await message.answer(_access_denied_text())
            return
        await message.answer(_start_text(read_snapshot_text()), reply_markup=main_menu_kb())

    @router.message(Command("help"))
    async def cmd_help(message: Message) -> None:
        if not _is_allowed(message, ctx.allowed_users):
            await message.answer(_access_denied_text())
            return
        await message.answer(_help_text(), reply_markup=main_menu_kb())

    @router.message(Command("status"))
    async def cmd_status(message: Message) -> None:
        if not _is_allowed(message, ctx.allowed_users):
            await message.answer(_access_denied_text())
            return
        await message.answer(read_snapshot_text(), reply_markup=main_menu_kb())

    @router.message(Command("diff"))
    async def cmd_diff(message: Message) -> None:
        if not _is_allowed(message, ctx.allowed_users):
            await message.answer(_access_denied_text())
            return
        await message.answer(read_diff_text(), reply_markup=main_menu_kb())

    @router.message(Command("report"))
    async def cmd_report(message: Message) -> None:
        if not _is_allowed(message, ctx.allowed_users):
            await message.answer(_access_denied_text())
            return
        await message.answer(read_report_text(), reply_markup=main_menu_kb())

    return router

from __future__ import annotations

import argparse
import html
import json
import logging
import os
from pathlib import Path

import yaml
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv

from .handlers import BotContext, build_router


def _load_config(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config_invalid")
    return data


def _find_root(config_path: Path | None = None) -> Path:
    env_root = os.getenv("SECOPS_BUDDY_ROOT")
    if env_root:
        p = Path(env_root).expanduser()
        if p.exists():
            return p.resolve()

    seeds: list[Path] = [Path.cwd()]
    if config_path:
        seeds.append(config_path)
        seeds.append(config_path.parent)
    seeds.append(Path(__file__).resolve())
    seeds.append(Path(__file__).resolve().parent)

    seen: set[Path] = set()
    for seed in seeds:
        base = seed if seed.is_dir() else seed.parent
        for cand in [base, *base.parents]:
            if cand in seen:
                continue
            seen.add(cand)
            if (cand / ".env").is_file() and (cand / "config" / "config.yml").is_file():
                return cand
            if (cand / "config" / "config.yml").is_file():
                return cand
            if (cand / ".env").is_file():
                return cand
    return Path.cwd().resolve()


def _default_config_path() -> Path:
    root = _find_root()
    return root / "config" / "config.yml"


def _init_env(root: Path) -> None:
    load_dotenv(root / ".env", override=False)


def _escape(s: str) -> str:
    return html.escape(s, quote=False)


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _get_allowed_users(env: os._Environ[str]) -> set[int]:
    env_multi = env.get("TELEGRAM_ALLOWED_USERS") or ""
    env_single = env.get("TELEGRAM_ALLOWED_USER") or ""

    raw_parts: list[str] = []
    if env_multi:
        raw_parts.extend([p.strip() for p in env_multi.replace(";", ",").split(",")])
    if env_single:
        raw_parts.append(env_single.strip())

    out: set[int] = set()
    for part in raw_parts:
        if not part:
            continue
        if " " in part:
            for sub in part.split():
                try:
                    out.add(int(sub))
                except Exception:
                    pass
            continue
        try:
            out.add(int(part))
        except Exception:
            pass
    return out


def _get_state_dir(root: Path, config: dict) -> Path:
    paths = config.get("paths") if isinstance(config.get("paths"), dict) else {}
    state_dir_raw = str(paths.get("state_dir") or "./var/secops-buddy")
    p = Path(state_dir_raw)
    return p if p.is_absolute() else (root / p).resolve()


def _format_status(snapshot: dict | None) -> str:
    if not snapshot:
        return "<b>Нет данных</b>\n\nСначала запусти agent, чтобы он создал snapshot."
    meta = snapshot.get("meta") if isinstance(snapshot.get("meta"), dict) else {}
    ts = _escape(str(meta.get("ts") or ""))
    parts: list[str] = []
    if ts:
        parts.append(f"<b>Последний snapshot</b> <code>{ts}</code>")
    for name in ("ssh", "ports", "firewall", "users", "logs", "updates"):
        item = snapshot.get(name)
        if not isinstance(item, dict):
            continue
        st = _escape(str(item.get("status") or ""))
        det = _escape(str(item.get("details") or ""))
        parts.append(f"<b>{_escape(name)}</b>: <code>{st}</code> {_escape(det)}")
    return "\n".join(parts) if parts else "<b>Нет данных</b>"


def _format_diff(diff: dict | None) -> str:
    if not diff:
        return "<b>Нет diff</b>\n\nЗапусти agent два раза, чтобы появился diff."
    st = _escape(str(diff.get("status") or ""))
    det = _escape(str(diff.get("details") or ""))
    data = diff.get("data") if isinstance(diff.get("data"), dict) else {}
    changed = data.get("changed") if isinstance(data.get("changed"), dict) else {}
    parts = [f"<b>Diff</b>: <code>{st}</code> {_escape(det)}"]
    if not changed:
        return "\n".join(parts)
    for k in sorted(changed.keys()):
        parts.append(f"- <b>{_escape(str(k))}</b>")
    return "\n".join(parts)


def _format_report(snapshot: dict | None, diff: dict | None) -> str:
    return f"{_format_status(snapshot)}\n\n{_format_diff(diff)}"


async def run_bot(config_path: str) -> None:
    cfg_path = Path(config_path).expanduser().resolve()
    root = _find_root(cfg_path)
    _init_env(root)
    config = _load_config(cfg_path)

    token = os.getenv("TELEGRAM_BOT_TOKEN") or ""
    if not token:
        raise RuntimeError("bot_token_missing")

    allowed = _get_allowed_users(os.environ)
    if not allowed:
        raise RuntimeError("allowed_users_missing")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.info("bot_start root=%s config=%s allowed_users=%d", root, cfg_path, len(allowed))

    state_dir = _get_state_dir(root, config)

    def read_snapshot_text() -> str:
        return _format_status(_read_json(state_dir / "snapshots" / "latest.json"))

    def read_diff_text() -> str:
        return _format_diff(_read_json(state_dir / "diffs" / "latest.json"))

    def read_report_text() -> str:
        snapshot = _read_json(state_dir / "snapshots" / "latest.json")
        diff = _read_json(state_dir / "diffs" / "latest.json")
        return _format_report(snapshot, diff)

    bot = Bot(
        token=token,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
        ),
    )
    dp = Dispatcher()
    ctx = BotContext(allowed_users=allowed, state_dir=state_dir)
    dp.include_router(build_router(ctx, read_snapshot_text, read_diff_text, read_report_text))
    await dp.start_polling(bot, allowed_updates=["message"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="secops_buddy.bot")
    parser.add_argument("--config", default=str(_default_config_path()))
    args = parser.parse_args(argv)

    import asyncio

    try:
        asyncio.run(run_bot(args.config))
    except Exception as e:
        raise SystemExit(str(e))
    return 0

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
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


def _format_snapshot(snapshot: dict | None) -> str:
    if not snapshot:
        return "<b>Нет данных</b>\n\nСначала запусти agent, чтобы он создал snapshot."
    meta = snapshot.get("meta") if isinstance(snapshot.get("meta"), dict) else {}
    ts = str(meta.get("ts") or "").strip()
    parts: list[str] = []
    if ts:
        parts.append(f"<b>Время</b>: <code>{_escape(_fmt_dt_human(ts))}</code>")
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
    return f"{_format_snapshot(snapshot)}\n\n{_format_diff(diff)}"


def _fmt_bytes(n: int) -> str:
    step = 1024.0
    x = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if x < step:
            return f"{x:.1f} {unit}"
        x /= step
    return f"{x:.1f} PiB"


def _read_meminfo() -> dict[str, int]:
    p = Path("/proc/meminfo")
    if not p.exists():
        return {}
    out: dict[str, int] = {}
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if ":" not in line:
            continue
        k, rest = line.split(":", 1)
        v = rest.strip().split()
        if not v:
            continue
        try:
            out[k] = int(v[0]) * 1024
        except Exception:
            pass
    return out


def _process_rss_bytes() -> int | None:
    statm = Path("/proc/self/statm")
    if not statm.exists():
        return None
    try:
        parts = statm.read_text(encoding="utf-8", errors="replace").strip().split()
        if len(parts) < 2:
            return None
        rss_pages = int(parts[1])
        page = os.sysconf("SC_PAGE_SIZE")
        return rss_pages * int(page)
    except Exception:
        return None


def _fmt_duration_s(s: float) -> str:
    s_i = max(0, int(s))
    h, rem = divmod(s_i, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}ч {m}м {sec}с"
    if m:
        return f"{m}м {sec}с"
    return f"{sec}с"


def _file_mtime_iso(p: Path) -> str | None:
    try:
        ts = p.stat().st_mtime
    except Exception:
        return None
    return datetime.fromtimestamp(ts).isoformat()


def _fmt_dt_human(iso_s: str | None) -> str:
    if not iso_s:
        return "нет"
    s = iso_s.strip()
    if not s:
        return "нет"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return _escape(s)
    try:
        dt = dt.astimezone()
    except Exception:
        pass
    return dt.strftime("%Y-%m-%d %H:%M")


def _last_logins_lines(limit: int = 5) -> list[str]:
    try:
        p = subprocess.run(
            ["last", "-i", "-n", str(limit)],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return []
    out = (p.stdout or "").splitlines()
    lines: list[str] = []
    for line in out:
        s = line.strip()
        if not s:
            continue
        if s.startswith("wtmp begins"):
            continue
        lines.append(s)
        if len(lines) >= limit:
            break
    return lines


def _format_last_login(line: str) -> str:
    parts = line.split()
    if len(parts) < 4:
        return f"<code>{_escape(line)}</code>"
    user = parts[0]
    ip = parts[2]
    rest = " ".join(parts[3:])
    status = "offline"
    if "still logged in" in rest:
        status = "online"
        rest = rest.replace("still logged in", "").strip()
    rest = rest.strip()
    if rest.endswith("-"):
        rest = rest[:-1].strip()
    return f"<code>{_escape(user)} | {_escape(ip)} | {_escape(rest)} | {_escape(status)}</code>"


def _local_ips() -> list[str]:
    ips: set[str] = set()
    try:
        p = subprocess.run(["hostname", "-I"], check=False, capture_output=True, text=True)
        for part in (p.stdout or "").split():
            s = part.strip()
            if s:
                ips.add(s)
    except Exception:
        pass

    if not ips:
        try:
            p = subprocess.run(["ip", "-o", "addr", "show"], check=False, capture_output=True, text=True)
            for line in (p.stdout or "").splitlines():
                parts = line.split()
                if "inet" in parts:
                    i = parts.index("inet")
                    if i + 1 < len(parts):
                        addr = parts[i + 1].split("/", 1)[0].strip()
                        if addr:
                            ips.add(addr)
                if "inet6" in parts:
                    i = parts.index("inet6")
                    if i + 1 < len(parts):
                        addr = parts[i + 1].split("/", 1)[0].strip()
                        if addr:
                            ips.add(addr)
        except Exception:
            pass

    def key(x: str) -> tuple[int, str]:
        return (0, x) if "." in x else (1, x)

    out = sorted(ips, key=key)
    return out


def _proto_hint(proto: str, port: int) -> str:
    p = proto.lower()
    if p.startswith("tcp"):
        if port == 22:
            return "ssh/sftp"
        if port in (80, 8080, 8000, 3000, 5000):
            return "http"
        if port in (443, 8443):
            return "https"
        return "tcp"
    if p.startswith("udp"):
        if port == 53:
            return "dns (udp)"
        if port == 123:
            return "ntp (udp)"
        return "udp"
    return p or "unknown"


def _format_endpoints(*, state_dir: Path) -> str:
    snap_path = state_dir / "snapshots" / "latest.json"
    snapshot = _read_json(snap_path)
    if not snapshot:
        return "<b>Как подключиться</b>\n\nНет snapshot. Сначала запусти agent."

    ports = snapshot.get("ports") if isinstance(snapshot.get("ports"), dict) else {}
    data = ports.get("data") if isinstance(ports.get("data"), dict) else {}
    entries = data.get("entries") if isinstance(data.get("entries"), list) else []

    ssh_port = 22
    ssh = snapshot.get("ssh") if isinstance(snapshot.get("ssh"), dict) else {}
    ssh_data = ssh.get("data") if isinstance(ssh.get("data"), dict) else {}
    ssh_cfg = ssh_data.get("config") if isinstance(ssh_data.get("config"), dict) else {}
    raw_port = ssh_cfg.get("Port")
    if isinstance(raw_port, str):
        try:
            ssh_port = int(raw_port.strip())
        except Exception:
            ssh_port = 22
    elif isinstance(raw_port, list) and raw_port:
        try:
            ssh_port = int(str(raw_port[0]).strip())
        except Exception:
            ssh_port = 22

    ips = _local_ips()
    if not ips:
        ips = ["127.0.0.1"]

    out: set[tuple[str, str]] = set()
    for e in entries:
        if not isinstance(e, dict):
            continue
        try:
            port = int(e.get("port") or 0)
        except Exception:
            port = 0
        if port <= 0:
            continue
        proto = str(e.get("proto") or "").strip().lower()
        ip = str(e.get("ip") or "").strip()
        hint = _proto_hint(proto, port)

        is_wild = ip in ("*", "0.0.0.0", "::", "")
        targets = ips if is_wild else [ip]

        for host in targets:
            addr = f"{host}:{port}"
            out.add((addr, hint))

    for host in ips:
        out.add((f"{host}:{ssh_port}", "ssh/sftp"))

    lines: list[str] = []
    lines.append("<b>Как подключиться к серверу</b>")
    lines.append("")
    lines.append("Список составлен по последнему snapshot (слушающие порты).")
    lines.append("Если сервер за NAT — используй внешний IP/домен и проброшенные порты.")
    lines.append("")
    lines.append("<b>Адрес | протокол</b>")
    lines.append("")
    if not out:
        lines.append("<code>Нет открытых слушающих портов в snapshot</code>")
        return "\n".join(lines)

    for addr, hint in sorted(out, key=lambda x: (x[1], x[0])):
        lines.append(f"<code>{_escape(addr)} | {_escape(hint)}</code>")
    return "\n".join(lines)

def _format_status(
    *,
    root: Path,
    config_path: Path,
    state_dir: Path,
    started_at: float,
) -> str:
    snap_path = state_dir / "snapshots" / "latest.json"
    diff_path = state_dir / "diffs" / "latest.json"

    mem = _read_meminfo()
    mem_avail = mem.get("MemAvailable")
    mem_total = mem.get("MemTotal")
    rss = _process_rss_bytes()
    up_s = max(0.0, time.time() - started_at)

    lines: list[str] = []
    lines.append("<b>Статус</b>")
    lines.append("")
    lines.append(f"<b>Бот</b>: работает <code>{_escape(_fmt_duration_s(up_s))}</code>")
    if mem_avail is not None and mem_total is not None:
        used = max(0, mem_total - mem_avail)
        pct_used = int(round((used / mem_total) * 100.0)) if mem_total else 0
        lines.append(
            f"<b>ОЗУ</b>: свободно <code>{_escape(_fmt_bytes(mem_avail))}</code> из <code>{_escape(_fmt_bytes(mem_total))}</code> (<code>{pct_used}%</code> занято)"
        )
    if rss is not None:
        if mem_total:
            pct = int(round((rss / mem_total) * 100.0))
            lines.append(f"<b>Бот использует ОЗУ</b>: <code>{_escape(_fmt_bytes(rss))}</code> (<code>{pct}%</code> от общей)")
        else:
            lines.append(f"<b>Бот использует ОЗУ</b>: <code>{_escape(_fmt_bytes(rss))}</code>")

    snap_m = _file_mtime_iso(snap_path)
    diff_m = _file_mtime_iso(diff_path)
    lines.append("")
    lines.append("<b>Последние данные</b>")
    lines.append(f"<b>Последний snapshot</b>: <code>{_escape(_fmt_dt_human(snap_m))}</code>")
    lines.append(f"<b>Последний diff</b>: <code>{_escape(_fmt_dt_human(diff_m))}</code>")

    logins = _last_logins_lines(5)
    lines.append("")
    lines.append("<b>Последние входы</b>")
    if logins:
        for ln in logins:
            lines.append(_format_last_login(ln))
    else:
        lines.append("<code>unavailable</code>")

    lines.append("")
    lines.append(f"<b>Корень проекта</b>: <code>{_escape(str(root))}</code>")

    snapshot = _read_json(snap_path)
    if snapshot:
        lines.append("")
        lines.append("<b>Детали snapshot</b>")
        lines.append(_format_snapshot(snapshot))

    return "\n".join(lines)


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
    started_at = time.time()

    def read_status_text() -> str:
        return _format_status(root=root, config_path=cfg_path, state_dir=state_dir, started_at=started_at)

    def read_endpoints_text() -> str:
        return _format_endpoints(state_dir=state_dir)

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
    ctx = BotContext(allowed_users=allowed, state_dir=state_dir, root=root, config_path=cfg_path)
    dp.include_router(build_router(ctx, read_status_text, read_endpoints_text, read_diff_text, read_report_text))
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

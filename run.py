import argparse
import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path

from secops_buddy.agent import run as run_agent
from secops_buddy.bot.app import run_bot
from secops_buddy.utils import find_root, init_env, load_config


def _pid_paths(root: Path) -> tuple[Path, Path, Path, Path]:
    logs_dir = root / "var" / "secops-buddy"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return (
        logs_dir / "secops-buddy.pid",
        logs_dir / "run.log",
        logs_dir / "bot.log",
        logs_dir / "agent.log",
        logs_dir / "restart.flag",
    )


def _tg_get_username(token: str) -> str | None:
    import urllib.request

    if not token:
        return None
    url = f"https://api.telegram.org/bot{token}/getMe"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = r.read().decode("utf-8", "ignore")
    except Exception:
        return None
    try:
        obj = json.loads(data)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    res = obj.get("result")
    if not isinstance(res, dict):
        return None
    username = res.get("username")
    return str(username) if isinstance(username, str) and username else None


class _NamePrefixFilter(logging.Filter):
    def __init__(self, prefixes: tuple[str, ...]):
        super().__init__()
        self.prefixes = prefixes

    def filter(self, record: logging.LogRecord) -> bool:
        return record.name.startswith(self.prefixes)


def _configure_logging(root: Path, bot_log: Path, agent_log: Path, run_log: Path) -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)

    h_run = logging.FileHandler(run_log, encoding="utf-8")
    h_run.setFormatter(fmt)
    h_run.addFilter(_NamePrefixFilter(("secops_buddy.run",)))
    root_logger.addHandler(h_run)

    h_bot = logging.FileHandler(bot_log, encoding="utf-8")
    h_bot.setFormatter(fmt)
    h_bot.addFilter(_NamePrefixFilter(("secops_buddy.bot", "aiogram")))
    root_logger.addHandler(h_bot)

    h_agent = logging.FileHandler(agent_log, encoding="utf-8")
    h_agent.setFormatter(fmt)
    h_agent.addFilter(_NamePrefixFilter(("secops_buddy.agent",)))
    root_logger.addHandler(h_agent)

    os.environ["SECOPS_BUDDY_AGENT_LOG"] = str(agent_log)

    logging.getLogger("secops_buddy.run").info("logging_ready root=%s", root)


 


async def _agent_loop_with_stop(stop: asyncio.Event, config_path: str, interval_s: int) -> None:
    log = logging.getLogger("secops_buddy.run")
    while not stop.is_set():
        try:
            os.environ["SECOPS_BUDDY_ARCHIVE"] = "0"
            await asyncio.to_thread(run_agent, config_path)
        except Exception as e:
            log.error("agent_error %s", e)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
        except TimeoutError:
            pass


async def _run(config_path: str, once: bool, no_agent: bool) -> None:
    log = logging.getLogger("secops_buddy.run")
    if not no_agent:
        try:
            await asyncio.to_thread(run_agent, config_path)
        except Exception as e:
            log.error("agent_error %s", e)

    if once:
        return

    cfg_path = Path(config_path).expanduser().resolve()
    root = find_root(cfg_path)
    config = load_config(cfg_path)
    interval_s = 10
    try:
        interval_s = int(config.get("monitor_interval_seconds") or 10)
    except Exception:
        interval_s = 10
    interval_s = max(2, interval_s)

    stop = asyncio.Event()
    restart = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_stop() -> None:
        stop.set()

    def request_restart() -> None:
        restart.set()
        stop.set()

    for sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, request_stop)
        except Exception:
            pass
    for sig in (getattr(signal, "SIGHUP", None), getattr(signal, "SIGUSR1", None)):
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, request_restart)
        except Exception:
            pass

    async def watch_restart_flag(path: Path) -> None:
        last = 0.0
        try:
            last = path.stat().st_mtime
        except Exception:
            last = 0.0
        while not stop.is_set():
            await asyncio.sleep(0.5)
            try:
                cur = path.stat().st_mtime
            except Exception:
                cur = 0.0
            if cur and cur != last:
                request_restart()
                return

    tasks: list[asyncio.Task] = []
    if not no_agent:
        tasks.append(asyncio.create_task(_agent_loop_with_stop(stop, config_path, interval_s)))
    tasks.append(asyncio.create_task(run_bot(config_path)))
    restart_flag = Path(os.getenv("SECOPS_BUDDY_RESTART_FLAG", "")).expanduser()
    if not restart_flag.name:
        restart_flag = (root / "var" / "secops-buddy" / "restart.flag").resolve()
    tasks.append(asyncio.create_task(watch_restart_flag(restart_flag)))

    log.info("run_start root=%s config=%s monitor_interval_s=%d", root, config_path, interval_s)
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
    except KeyboardInterrupt:
        stop.set()
    finally:
        stop.set()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if restart.is_set():
            args = [sys.executable, str(Path(__file__).resolve()), "--config", str(cfg_path)]
            if no_agent:
                args.append("--no-agent")
            args.append("--foreground")
            os.execv(sys.executable, args)


parser = argparse.ArgumentParser(prog="run")
parser.add_argument("--config", default=str(find_root() / "config" / "config.yml"))
parser.add_argument("--once", action="store_true")
parser.add_argument("--no-agent", action="store_true")
parser.add_argument("--foreground", action="store_true")
args = parser.parse_args()

cfg_path = Path(args.config).expanduser().resolve()
root = find_root(cfg_path)
init_env(cfg_path)

pid_path, run_log, bot_log, agent_log, restart_flag = _pid_paths(root)
os.environ["SECOPS_BUDDY_RESTART_FLAG"] = str(restart_flag)

token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
bot_username = _tg_get_username(token)

is_child = os.getenv("SECOPS_BUDDY_DAEMON", "").strip() == "1"
can_daemon = os.name == "posix" and not args.foreground and not is_child and not args.once

if can_daemon:
    env = dict(os.environ)
    env["SECOPS_BUDDY_DAEMON"] = "1"
    env["SECOPS_BUDDY_ROOT"] = str(root)

    out = open(run_log, "a", encoding="utf-8")
    try:
        p = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--config", str(cfg_path), "--foreground", *([] if not args.no_agent else ["--no-agent"])],
            cwd=str(root),
            env=env,
            stdout=out,
            stderr=out,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    finally:
        out.close()

    pid_path.write_text(str(p.pid), encoding="utf-8")

    print("secops-buddy started")
    if bot_username:
        print(f"bot: @{bot_username}")
    else:
        print("bot: unavailable")
    print(f"pid: {p.pid}")
    print("logs:")
    print(f"  tail -f {run_log}")
    print(f"  tail -f {bot_log}")
    print(f"  tail -f {agent_log}")
    print("stop:")
    print(f"  kill $(cat {pid_path})")
    raise SystemExit(0)

_configure_logging(root, bot_log, agent_log, run_log)

raise SystemExit(asyncio.run(_run(str(cfg_path), args.once, args.no_agent)))

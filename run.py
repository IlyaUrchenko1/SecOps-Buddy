import argparse
import asyncio
import logging
import os
import signal
from pathlib import Path

import yaml
from dotenv import load_dotenv

from secops_buddy.agent import run as run_agent
from secops_buddy.bot.app import run_bot


def _find_root() -> Path:
    env_root = os.getenv("SECOPS_BUDDY_ROOT")
    if env_root:
        p = Path(env_root).expanduser()
        if p.exists():
            return p.resolve()

    seeds = [Path.cwd(), Path(__file__).resolve(), Path(__file__).resolve().parent]
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


def _load_config(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config_invalid")
    return data


 


async def _agent_loop_with_stop(stop: asyncio.Event, config_path: str, interval_s: int) -> None:
    while not stop.is_set():
        try:
            await asyncio.to_thread(run_agent, config_path)
        except Exception as e:
            logging.error("agent_error %s", e)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
        except TimeoutError:
            pass


async def _run(config_path: str, once: bool, no_agent: bool) -> None:
    if not no_agent:
        try:
            await asyncio.to_thread(run_agent, config_path)
        except Exception as e:
            logging.error("agent_error %s", e)

    if once:
        return

    root = _find_root()
    config = _load_config(Path(config_path).expanduser().resolve())
    interval_h = 24
    try:
        interval_h = int(config.get("scan_interval_hours") or 24)
    except Exception:
        interval_h = 24
    interval_s = max(60, interval_h * 3600)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_stop() -> None:
        stop.set()

    for sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, request_stop)
        except Exception:
            pass

    tasks: list[asyncio.Task] = []
    if not no_agent:
        tasks.append(asyncio.create_task(_agent_loop_with_stop(stop, config_path, interval_s)))
    tasks.append(asyncio.create_task(run_bot(config_path)))

    logging.info("run_start root=%s config=%s interval_s=%d", root, config_path, interval_s)
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
    except KeyboardInterrupt:
        stop.set()
    finally:
        stop.set()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


parser = argparse.ArgumentParser(prog="run")
parser.add_argument("--config", default=str(_find_root() / "config" / "config.yml"))
parser.add_argument("--once", action="store_true")
parser.add_argument("--no-agent", action="store_true")
args = parser.parse_args()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
root = _find_root()
load_dotenv(root / ".env", override=False)

raise SystemExit(asyncio.run(_run(args.config, args.once, args.no_agent)))

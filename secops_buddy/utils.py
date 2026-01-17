from __future__ import annotations

import json
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv


def find_root(config_path: Path | None = None) -> Path:
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


def default_config_path() -> Path:
    root = find_root()
    return root / "config" / "config.yml"


def load_config(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config_invalid")
    return data


def init_env(config_path: Path) -> None:
    load_dotenv(find_root(config_path).joinpath(".env"), override=False)


def read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def write_json(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    tmp.replace(path)


def env_allowed_users() -> list[int]:
    raw = (os.getenv("TELEGRAM_ALLOWED_USERS") or "").strip()
    if not raw:
        raw = (os.getenv("TELEGRAM_ALLOWED_USER") or "").strip()
    if not raw:
        return []
    parts = raw.replace(";", ",").replace(" ", ",").split(",")
    out: list[int] = []
    for p in parts:
        s = p.strip()
        if not s:
            continue
        try:
            out.append(int(s))
        except Exception:
            pass
    return out

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

from secops_buddy.checks import check_ports, check_ssh
from secops_buddy.checks.firewall import check_firewall
from secops_buddy.checks.logs import check_logs
from secops_buddy.checks.updates import check_updates
from secops_buddy.checks.users import check_users


def _load_config(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config_invalid")
    return data


def _init_env(config_path: Path) -> None:
    load_dotenv(_find_root(config_path).joinpath(".env"), override=False)


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


def _ensure_dirs(state_dir: Path) -> tuple[Path, Path]:
    snapshots_dir = state_dir / "snapshots"
    diffs_dir = state_dir / "diffs"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    diffs_dir.mkdir(parents=True, exist_ok=True)
    return snapshots_dir, diffs_dir


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _write_json(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    tmp.replace(path)


def _diff(prev: dict | None, cur: dict) -> dict:
    if not prev:
        return {"status": "ok", "details": "no_previous_snapshot", "data": {"changed": {}}}
    changed: dict[str, dict] = {}
    for k, v in cur.items():
        if k in ("meta",):
            continue
        pv = prev.get(k)
        if pv != v:
            changed[k] = {"before": pv, "after": v}
    for k in prev.keys():
        if k in ("meta",):
            continue
        if k not in cur:
            changed[k] = {"before": prev.get(k), "after": None}
    status = "ok" if not changed else "warn"
    details = "no_changes" if not changed else f"changed={len(changed)}"
    return {"status": status, "details": details, "data": {"changed": changed}}


def _collect_snapshot(config: dict) -> dict:
    checks_cfg = config.get("checks") if isinstance(config.get("checks"), dict) else {}
    snapshot: dict[str, object] = {
        "meta": {
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    }
    if checks_cfg.get("ports", True):
        snapshot["ports"] = check_ports()
    if checks_cfg.get("ssh", True):
        snapshot["ssh"] = check_ssh()
    if checks_cfg.get("firewall", False):
        snapshot["firewall"] = check_firewall()
    if checks_cfg.get("users", False):
        snapshot["users"] = check_users()
    if checks_cfg.get("logs", False):
        snapshot["logs"] = check_logs()
    if checks_cfg.get("updates", False):
        snapshot["updates"] = check_updates()
    return snapshot


def run(config_path: str) -> int:
    cfg_path = Path(config_path).expanduser().resolve()
    config = _load_config(cfg_path)
    _init_env(cfg_path)

    paths = config.get("paths") if isinstance(config.get("paths"), dict) else {}
    root = _find_root(cfg_path)
    state_dir_raw = str(paths.get("state_dir") or "./var/secops-buddy")
    log_file_raw = str(paths.get("log_file") or "./var/secops-buddy/secops-buddy.log")

    state_dir = Path(state_dir_raw)
    if not state_dir.is_absolute():
        state_dir = (root / state_dir).resolve()

    log_file = Path(log_file_raw)
    if not log_file.is_absolute():
        log_file = (root / log_file).resolve()

    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8")],
    )

    snapshots_dir, diffs_dir = _ensure_dirs(state_dir)
    latest_snapshot = snapshots_dir / "latest.json"
    latest_diff = diffs_dir / "latest.json"

    prev = _read_json(latest_snapshot)
    cur = _collect_snapshot(config)
    diff = _diff(prev, cur)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot_ts_path = snapshots_dir / f"{ts}.json"
    diff_ts_path = diffs_dir / f"{ts}.json"

    _write_json(snapshot_ts_path, cur)
    _write_json(latest_snapshot, cur)
    _write_json(diff_ts_path, diff)
    _write_json(latest_diff, diff)

    logging.info("snapshot_saved ts=%s", ts)
    logging.info("diff status=%s details=%s", diff.get("status"), diff.get("details"))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="secops_buddy.agent")
    parser.add_argument("--config", default=str(_default_config_path()))
    args = parser.parse_args(argv)
    return run(args.config)


if __name__ == "__main__":
    raise SystemExit(main())

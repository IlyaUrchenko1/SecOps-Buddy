from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from secops_buddy.checks import check_ports, check_ssh
from secops_buddy.checks.firewall import check_firewall
from secops_buddy.checks.logs import check_logs
from secops_buddy.checks.updates import check_updates
from secops_buddy.checks.users import check_users
from secops_buddy.notifications import NotificationManager
from secops_buddy.utils import (
    default_config_path,
    env_allowed_users,
    find_root,
    init_env,
    load_config,
    read_json,
    write_json,
)




def _ensure_dirs(state_dir: Path) -> tuple[Path, Path]:
    snapshots_dir = state_dir / "snapshots"
    diffs_dir = state_dir / "diffs"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    diffs_dir.mkdir(parents=True, exist_ok=True)
    return snapshots_dir, diffs_dir


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
    notif_cfg = config.get("notifications") if isinstance(config.get("notifications"), dict) else {}
    notif_enabled = bool(notif_cfg.get("enabled", True))
    snapshot: dict[str, object] = {
        "meta": {
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    }
    if checks_cfg.get("ports", True) or notif_enabled:
        snapshot["ports"] = check_ports()
    if checks_cfg.get("ssh", True) or notif_enabled:
        snapshot["ssh"] = check_ssh()
    if checks_cfg.get("firewall", False) or notif_enabled:
        snapshot["firewall"] = check_firewall()
    if checks_cfg.get("users", False) or notif_enabled:
        snapshot["users"] = check_users()
    if checks_cfg.get("logs", False) or notif_enabled:
        snapshot["logs"] = check_logs()
    if checks_cfg.get("updates", False) or notif_enabled:
        snapshot["updates"] = check_updates()
    return snapshot


def _notify(config: dict, state_dir: Path, cur: dict) -> None:
    notif_cfg = config.get("notifications") if isinstance(config.get("notifications"), dict) else {}
    if not bool(notif_cfg.get("enabled", True)):
        return
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        return
    recipients = env_allowed_users()
    if not recipients:
        return
    
    st_path = state_dir / "notify_state.json"
    st = read_json(st_path)
    if not isinstance(st, dict):
        st = {}

    send_warning = bool(notif_cfg.get("send_warning", True))
    send_critical = bool(notif_cfg.get("send_critical", True))

    mgr = NotificationManager(token, recipients, send_warning, send_critical)
    mgr.check_new_ips(cur, st)
    mgr.check_ports(cur, st)
    mgr.check_sudo_users(cur, st)
    mgr.check_updates(cur, st)
    mgr.check_logs(cur, st)
    mgr.check_firewall(cur, st)
    mgr.send_all()

    next_state = mgr.build_next_state(cur)
    try:
        write_json(st_path, next_state)
    except Exception:
        return


def run(config_path: str) -> int:
    cfg_path = Path(config_path).expanduser().resolve()
    config = load_config(cfg_path)
    init_env(cfg_path)

    paths = config.get("paths") if isinstance(config.get("paths"), dict) else {}
    root = find_root(cfg_path)
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
    archive = os.getenv("SECOPS_BUDDY_ARCHIVE", "1").strip() not in {"0", "false", "False", "no", "NO"}

    prev = read_json(latest_snapshot)
    cur = _collect_snapshot(config)
    diff = _diff(prev, cur)
    _notify(config, state_dir, cur)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot_ts_path = snapshots_dir / f"{ts}.json"
    diff_ts_path = diffs_dir / f"{ts}.json"

    if archive:
        write_json(snapshot_ts_path, cur)
    write_json(latest_snapshot, cur)
    if archive:
        write_json(diff_ts_path, diff)
    write_json(latest_diff, diff)

    logging.info("snapshot_saved ts=%s", ts)
    logging.info("diff status=%s details=%s", diff.get("status"), diff.get("details"))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="secops_buddy.agent")
    parser.add_argument("--config", default=str(default_config_path()))
    args = parser.parse_args(argv)
    return run(args.config)


if __name__ == "__main__":
    raise SystemExit(main())

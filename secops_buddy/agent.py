from __future__ import annotations

import argparse
import json
import logging
import os
import urllib.parse
import urllib.request
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


def _read_state(path: Path) -> dict:
    data = _read_json(path)
    return data if isinstance(data, dict) else {}


def _write_state(path: Path, payload: dict) -> None:
    _write_json(path, payload)


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
    if checks_cfg.get("firewall", False):
        snapshot["firewall"] = check_firewall()
    if checks_cfg.get("users", False) or notif_enabled:
        snapshot["users"] = check_users()
    if checks_cfg.get("logs", False) or notif_enabled:
        snapshot["logs"] = check_logs()
    if checks_cfg.get("updates", False) or notif_enabled:
        snapshot["updates"] = check_updates()
    return snapshot


def _env_allowed_users() -> list[int]:
    raw = (os.getenv("TELEGRAM_ALLOWED_USERS") or "").strip()
    if not raw:
        raw = (os.getenv("TELEGRAM_ALLOWED_USER") or "").strip()
    if not raw:
        return []
    parts: list[str] = []
    for chunk in raw.replace(";", ",").split(","):
        s = chunk.strip()
        if not s:
            continue
        if " " in s:
            parts.extend([x for x in s.split() if x.strip()])
        else:
            parts.append(s)
    out: list[int] = []
    for p in parts:
        try:
            out.append(int(p))
        except Exception:
            pass
    return sorted(set(out))


def _tg_send(token: str, chat_id: int, text: str) -> None:
    payload = {
        "chat_id": str(chat_id),
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }
    data = urllib.parse.urlencode(payload).encode("utf-8")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=10) as _:
        return


def _notify(config: dict, state_dir: Path, cur: dict) -> None:
    notif_cfg = config.get("notifications") if isinstance(config.get("notifications"), dict) else {}
    if not bool(notif_cfg.get("enabled", True)):
        return
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        return
    recipients = _env_allowed_users()
    if not recipients:
        return
    st_path = state_dir / "notify_state.json"
    st = _read_state(st_path)

    send_warning = bool(notif_cfg.get("send_warning", True))
    send_critical = bool(notif_cfg.get("send_critical", True))

    msgs: list[tuple[str, str]] = []

    cur_logs = cur.get("logs") if isinstance(cur.get("logs"), dict) else {}
    cur_ips = set()
    if isinstance(cur_logs.get("data"), dict):
        cur_ips = set((cur_logs["data"].get("ips") or []) if isinstance(cur_logs["data"].get("ips"), list) else [])
    prev_ips = set(st.get("ips") or []) if isinstance(st.get("ips"), list) else set()
    new_ips = sorted([ip for ip in (cur_ips - prev_ips) if isinstance(ip, str) and ip and ip != "0.0.0.0"])
    if new_ips and send_warning:
        msgs.append(("warn", "<b>Новый IP входа</b>\n" + "\n".join([f"<code>{ip}</code>" for ip in new_ips[:10]])))

    cur_ports = cur.get("ports") if isinstance(cur.get("ports"), dict) else {}
    def port_set(x: dict) -> set[tuple[str, str, int]]:
        data = x.get("data") if isinstance(x.get("data"), dict) else {}
        entries = data.get("entries") if isinstance(data.get("entries"), list) else []
        out: set[tuple[str, str, int]] = set()
        for e in entries:
            if not isinstance(e, dict):
                continue
            proto = str(e.get("proto") or "").strip().lower()
            ip = str(e.get("ip") or "").strip()
            try:
                port = int(e.get("port") or 0)
            except Exception:
                port = 0
            if port > 0 and proto:
                out.add((proto, ip, port))
        return out
    prev_ports_state = st.get("ports")
    prev_ps = set()
    if isinstance(prev_ports_state, list):
        for t in prev_ports_state:
            if isinstance(t, list) and len(t) == 3:
                proto, ip, port = t
                if isinstance(proto, str) and isinstance(ip, str) and isinstance(port, int):
                    prev_ps.add((proto, ip, port))
    cur_ps = port_set(cur_ports)
    added = sorted(cur_ps - prev_ps)
    removed = sorted(prev_ps - cur_ps)
    if (added or removed) and send_warning:
        lines: list[str] = ["<b>Изменились порты</b>"]
        if added:
            lines.append("")
            lines.append("<b>Открылись</b>")
            for proto, ip, port in added[:15]:
                lines.append(f"<code>{ip}:{port} | {proto}</code>")
        if removed:
            lines.append("")
            lines.append("<b>Закрылись</b>")
            for proto, ip, port in removed[:15]:
                lines.append(f"<code>{ip}:{port} | {proto}</code>")
        msgs.append(("warn", "\n".join(lines)))

    cur_users = cur.get("users") if isinstance(cur.get("users"), dict) else {}
    def sudo_set(x: dict) -> set[str]:
        data = x.get("data") if isinstance(x.get("data"), dict) else {}
        lst = data.get("sudo_users") if isinstance(data.get("sudo_users"), list) else []
        return set([str(u) for u in lst if isinstance(u, str) and u.strip()])
    prev_sudo = set(st.get("sudo_users") or []) if isinstance(st.get("sudo_users"), list) else set()
    cur_sudo = sudo_set(cur_users)
    new_sudo = sorted(cur_sudo - prev_sudo)
    if new_sudo and send_critical:
        msgs.append(("crit", "<b>Новый sudo-пользователь</b>\n" + "\n".join([f"<code>{u}</code>" for u in new_sudo[:20]])))

    cur_upd = cur.get("updates") if isinstance(cur.get("updates"), dict) else {}
    def upd_count(x: dict) -> int:
        data = x.get("data") if isinstance(x.get("data"), dict) else {}
        try:
            return int(data.get("count") or 0)
        except Exception:
            return 0
    pc = int(st.get("updates_count") or 0) if isinstance(st.get("updates_count"), int) else 0
    cc = upd_count(cur_upd)
    if cc > 0 and pc == 0 and send_warning:
        pkgs = []
        data = cur_upd.get("data") if isinstance(cur_upd.get("data"), dict) else {}
        if isinstance(data.get("packages"), list):
            pkgs = [str(x) for x in data.get("packages")[:10]]
        text = f"<b>Доступны обновления</b>\n<code>{cc}</code> пакетов"
        if pkgs:
            text += "\n\n" + "\n".join([f"<code>{p}</code>" for p in pkgs])
        msgs.append(("warn", text))

    cur_log_status = str(cur_logs.get("status") or "")
    prev_log_status = str(st.get("logs_status") or "")
    if cur_log_status in {"warn", "crit"}:
        data = cur_logs.get("data") if isinstance(cur_logs.get("data"), dict) else {}
        ft = int(data.get("failed_total") or 0) if isinstance(data.get("failed_total"), int) else 0
        fr = int(data.get("failed_root") or 0) if isinstance(data.get("failed_root"), int) else 0
        iu = int(data.get("invalid_user") or 0) if isinstance(data.get("invalid_user"), int) else 0
        if cur_log_status != prev_log_status:
            if cur_log_status == "crit" and send_critical:
                msgs.append(("crit", f"<b>Критичные события в логах</b>\nfailed_total=<code>{ft}</code> failed_root=<code>{fr}</code> invalid_user=<code>{iu}</code>"))
            if cur_log_status == "warn" and send_warning:
                msgs.append(("warn", f"<b>Предупреждения в логах</b>\nfailed_total=<code>{ft}</code> invalid_user=<code>{iu}</code>"))

    for level, text in msgs:
        if level == "crit" and not send_critical:
            continue
        if level == "warn" and not send_warning:
            continue
        for uid in recipients:
            try:
                _tg_send(token, uid, text)
            except Exception:
                continue

    next_state = {
        "ips": sorted([ip for ip in cur_ips if isinstance(ip, str)]),
        "ports": sorted([list(x) for x in cur_ps]),
        "sudo_users": sorted([u for u in cur_sudo if isinstance(u, str)]),
        "updates_count": cc,
        "logs_status": cur_log_status,
    }
    try:
        _write_state(st_path, next_state)
    except Exception:
        return


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
    archive = os.getenv("SECOPS_BUDDY_ARCHIVE", "1").strip() not in {"0", "false", "False", "no", "NO"}

    prev = _read_json(latest_snapshot)
    cur = _collect_snapshot(config)
    diff = _diff(prev, cur)
    _notify(config, state_dir, cur)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot_ts_path = snapshots_dir / f"{ts}.json"
    diff_ts_path = diffs_dir / f"{ts}.json"

    if archive:
        _write_json(snapshot_ts_path, cur)
    _write_json(latest_snapshot, cur)
    if archive:
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

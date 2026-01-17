from __future__ import annotations

import re
import subprocess
from pathlib import Path


def check_logs() -> dict:
    sessions: list[dict] = []
    ips: set[str] = set()

    try:
        p = subprocess.run(
            ["last", "-i", "-n", "50"],
            check=False,
            capture_output=True,
            text=True,
        )
        for line in (p.stdout or "").splitlines():
            s = line.strip()
            if not s:
                continue
            if s.startswith("wtmp begins"):
                continue
            parts = s.split()
            if len(parts) >= 3:
                user = parts[0]
                ip = parts[2]
                if ip and ip != "0.0.0.0":
                    ips.add(ip)
                sessions.append({"user": user, "ip": ip, "raw": s})
    except Exception:
        pass

    def tail_lines(path: Path, max_bytes: int = 256_000) -> list[str]:
        try:
            with path.open("rb") as f:
                try:
                    f.seek(0, 2)
                    size = f.tell()
                    f.seek(max(0, size - max_bytes), 0)
                except Exception:
                    pass
                data = f.read()
        except Exception:
            return []
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            return []
        return text.splitlines()

    auth_path = Path("/var/log/auth.log")
    secure_path = Path("/var/log/secure")
    src = auth_path if auth_path.exists() else (secure_path if secure_path.exists() else None)

    failed_total = 0
    failed_root = 0
    invalid_user = 0
    if src:
        failed_re = re.compile(r"Failed password", re.IGNORECASE)
        invalid_re = re.compile(r"Invalid user", re.IGNORECASE)
        root_re = re.compile(r"\bfor\s+root\b", re.IGNORECASE)
        for line in tail_lines(src):
            if invalid_re.search(line):
                invalid_user += 1
            if failed_re.search(line):
                failed_total += 1
                if root_re.search(line):
                    failed_root += 1

    status = "ok"
    if failed_root > 0:
        status = "crit"
    elif failed_total > 0 or invalid_user > 0:
        status = "warn"

    details = f"failed={failed_total} invalid={invalid_user}"
    return {
        "status": status,
        "details": details,
        "data": {
            "ips": sorted(ips),
            "sessions": sessions[:50],
            "auth_log": str(src) if src else None,
            "failed_total": failed_total,
            "failed_root": failed_root,
            "invalid_user": invalid_user,
        },
    }

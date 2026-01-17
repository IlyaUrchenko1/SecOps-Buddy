from __future__ import annotations

import subprocess
from pathlib import Path


def check_updates() -> dict:
    apt = Path("/usr/bin/apt-get")
    if not apt.exists():
        return {
            "status": "warn",
            "details": "updates_check_unsupported",
            "data": {"backend": "none"},
        }

    try:
        p = subprocess.run(
            ["apt-get", "-s", "upgrade"],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception as e:
        return {
            "status": "warn",
            "details": "updates_check_failed",
            "data": {"backend": "apt", "error": str(e)},
        }

    pkgs: list[str] = []
    for line in (p.stdout or "").splitlines():
        s = line.strip()
        if not s.startswith("Inst "):
            continue
        parts = s.split()
        if len(parts) >= 2:
            pkgs.append(parts[1])

    pkgs = sorted(set(pkgs))
    count = len(pkgs)
    status = "ok" if count == 0 else "warn"
    return {
        "status": status,
        "details": f"updates={count}",
        "data": {"backend": "apt", "count": count, "packages": pkgs[:50]},
    }
    return {
        "status": "warn",
        "details": "not_implemented",
        "data": {},
    }

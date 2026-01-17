from __future__ import annotations

import subprocess
from pathlib import Path


def check_firewall() -> dict:
    ufw = Path("/usr/sbin/ufw")
    firewall_cmd = Path("/usr/bin/firewall-cmd")

    backend = "none"
    enabled = None
    rules: list[str] = []
    raw: dict[str, str] = {}

    if ufw.exists():
        backend = "ufw"
        p = subprocess.run(["ufw", "status"], check=False, capture_output=True, text=True)
        out = (p.stdout or "").strip()
        raw["status"] = out
        if "Status: active" in out:
            enabled = True
        elif "Status: inactive" in out:
            enabled = False

        p2 = subprocess.run(["ufw", "status", "numbered"], check=False, capture_output=True, text=True)
        out2 = (p2.stdout or "").splitlines()
        raw["rules"] = "\n".join(out2).strip()
        for line in out2:
            s = line.strip()
            if not s:
                continue
            if s.startswith("Status:"):
                continue
            if s.startswith("To"):
                continue
            if s.startswith("["):
                parts = s.split()
                if len(parts) >= 3:
                    to = parts[1]
                    action = parts[2]
                    rules.append(f"{to} {action}".strip())

    elif firewall_cmd.exists():
        backend = "firewalld"
        p = subprocess.run(["firewall-cmd", "--state"], check=False, capture_output=True, text=True)
        st = (p.stdout or "").strip().lower()
        raw["state"] = st
        enabled = st == "running"

        p2 = subprocess.run(["firewall-cmd", "--list-all"], check=False, capture_output=True, text=True)
        out2 = (p2.stdout or "").splitlines()
        raw["list_all"] = "\n".join(out2).strip()
        ports = ""
        services = ""
        for line in out2:
            s = line.strip()
            if s.startswith("ports:"):
                ports = s.split(":", 1)[1].strip()
            if s.startswith("services:"):
                services = s.split(":", 1)[1].strip()
        if services:
            for svc in services.split():
                rules.append(f"service:{svc}")
        if ports:
            for prt in ports.split():
                rules.append(prt)

    if backend == "none":
        return {
            "status": "warn",
            "details": "firewall_unsupported",
            "data": {"backend": backend},
        }

    rules = sorted(set([r for r in rules if r]))

    if enabled is False:
        status = "crit"
    elif enabled is True:
        status = "ok"
    else:
        status = "warn"

    details = f"{backend} {'active' if enabled else 'inactive' if enabled is False else 'unknown'} rules={len(rules)}"
    return {
        "status": status,
        "details": details,
        "data": {
            "backend": backend,
            "enabled": enabled,
            "rules": rules[:200],
            "raw": raw,
        },
    }

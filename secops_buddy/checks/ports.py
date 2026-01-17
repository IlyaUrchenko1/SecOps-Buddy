from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PortEntry:
    proto: str
    ip: str
    port: int
    process: str | None
    raw: str


_SS_RE = re.compile(r"^\S+")


def _split_host_port(local: str) -> tuple[str, int] | None:
    s = local.strip()
    if s == "*:*":
        return ("*", 0)
    if s.endswith(":*"):
        host = s[:-2]
        return (host, 0)
    if s.startswith("[") and "]:" in s:
        host, port_s = s[1:].split("]:", 1)
        try:
            return (host, int(port_s))
        except ValueError:
            return None
    if ":" in s:
        host, port_s = s.rsplit(":", 1)
        try:
            return (host, int(port_s))
        except ValueError:
            return None
    return None


def _parse_ss_lines(lines: list[str]) -> list[PortEntry]:
    out: list[PortEntry] = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        m = _SS_RE.match(s)
        if not m:
            continue
        parts = s.split()
        if len(parts) < 2:
            continue
        proto = parts[0].strip()
        if len(parts) >= 2 and parts[1].strip().upper() in {"LISTEN", "UNCONN"}:
            local = parts[-2] if len(parts) >= 2 else ""
        else:
            local = parts[-2] if len(parts) >= 2 else ""
        hp = _split_host_port(local)
        if not hp:
            continue
        ip, port = hp
        process = None
        out.append(
            PortEntry(
                proto=proto,
                ip=ip,
                port=port,
                process=process,
                raw=line,
            )
        )
    out.sort(key=lambda e: (e.proto, e.ip, e.port, e.process or ""))
    return out


def check_ports() -> dict:
    p = subprocess.run(
        ["ss", "-H", "-lntu"],
        check=False,
        capture_output=True,
        text=True,
    )
    stdout = (p.stdout or "").strip()
    stderr = (p.stderr or "").strip()
    lines = [ln for ln in stdout.splitlines() if ln.strip()]
    entries = _parse_ss_lines(lines)
    status = "ok" if p.returncode == 0 else "warn"
    details = f"entries={len(entries)}"
    return {
        "status": status,
        "details": details,
        "data": {
            "returncode": p.returncode,
            "stderr": stderr,
            "entries": [
                {
                    "proto": e.proto,
                    "ip": e.ip,
                    "port": e.port,
                    "process": e.process,
                    "raw": e.raw,
                }
                for e in entries
            ],
        },
    }

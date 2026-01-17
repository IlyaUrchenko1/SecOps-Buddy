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


_SS_RE = re.compile(r"^(?P<proto>\S+)\s+(?P<local>\S+)\s+(?P<peer>\S+)\s+(?P<process>.*)$")


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
        m = _SS_RE.match(line.strip())
        if not m:
            continue
        local = m.group("local")
        hp = _split_host_port(local)
        if not hp:
            continue
        ip, port = hp
        process_raw = m.group("process").strip()
        process = process_raw if process_raw else None
        out.append(
            PortEntry(
                proto=m.group("proto"),
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
        ["ss", "-tulpnH"],
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
            "entries": [e.__dict__ for e in entries],
        },
    }

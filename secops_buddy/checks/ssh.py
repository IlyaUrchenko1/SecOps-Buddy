from __future__ import annotations

from pathlib import Path


def _parse_sshd_config(text: str) -> dict[str, str | list[str]]:
    out: dict[str, str | list[str]] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        k = parts[0].strip()
        v = " ".join(parts[1:]).strip()
        prev = out.get(k)
        if prev is None:
            out[k] = v
        elif isinstance(prev, list):
            prev.append(v)
        else:
            out[k] = [prev, v]
    return out


def check_ssh(config_path: str = "/etc/ssh/sshd_config") -> dict:
    path = Path(config_path)
    if not path.exists():
        return {
            "status": "warn",
            "details": "sshd_config_not_found",
            "data": {"path": str(path)},
        }
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {
            "status": "warn",
            "details": "sshd_config_read_failed",
            "data": {"path": str(path), "error": str(e)},
        }
    parsed = _parse_sshd_config(text)
    keys = [
        "Port",
        "PermitRootLogin",
        "PasswordAuthentication",
        "PubkeyAuthentication",
        "ChallengeResponseAuthentication",
        "UsePAM",
        "KbdInteractiveAuthentication",
        "AuthenticationMethods",
        "AllowUsers",
        "AllowGroups",
        "DenyUsers",
        "DenyGroups",
    ]
    selected = {k: parsed.get(k) for k in keys if k in parsed}
    port = selected.get("Port")
    details = f"port={port}" if isinstance(port, str) else "parsed"
    return {
        "status": "ok",
        "details": details,
        "data": {"path": str(path), "config": selected},
    }

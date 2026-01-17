from __future__ import annotations

import subprocess

def check_users() -> dict:
    sudo_users: set[str] = set()

    def parse_getent(group: str) -> None:
        try:
            p = subprocess.run(["getent", "group", group], check=False, capture_output=True, text=True)
        except Exception:
            return
        if p.returncode != 0:
            return
        line = (p.stdout or "").strip()
        if not line:
            return
        parts = line.split(":", 3)
        if len(parts) != 4:
            return
        members = parts[3].strip()
        if not members:
            return
        for m in members.split(","):
            s = m.strip()
            if s:
                sudo_users.add(s)

    def parse_etc_group() -> None:
        try:
            import grp

            for gname in ("sudo", "wheel"):
                try:
                    g = grp.getgrnam(gname)
                except KeyError:
                    continue
                for u in g.gr_mem:
                    if u:
                        sudo_users.add(u)
        except Exception:
            return

    parse_getent("sudo")
    parse_getent("wheel")
    if not sudo_users:
        parse_etc_group()

    out = sorted(sudo_users)
    return {
        "status": "ok",
        "details": f"sudo_users={len(out)}",
        "data": {"sudo_users": out},
    }

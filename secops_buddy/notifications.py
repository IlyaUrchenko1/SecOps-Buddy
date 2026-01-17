from __future__ import annotations

import os
import urllib.parse
import urllib.request


def send_telegram(token: str, user_id: int, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": user_id, "text": text, "parse_mode": "HTML"}).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


class NotificationManager:
    def __init__(self, token: str, recipients: list[int], send_warning: bool, send_critical: bool):
        self.token = token
        self.recipients = recipients
        self.send_warning = send_warning
        self.send_critical = send_critical
        self.messages: list[tuple[str, str]] = []

    def add(self, level: str, text: str) -> None:
        self.messages.append((level, text))

    def send_all(self) -> None:
        for level, text in self.messages:
            if level == "crit" and not self.send_critical:
                continue
            if level == "warn" and not self.send_warning:
                continue
            for uid in self.recipients:
                try:
                    send_telegram(self.token, uid, text)
                except Exception:
                    continue

    def check_new_ips(self, cur: dict, prev_state: dict) -> None:
        cur_logs = cur.get("logs") if isinstance(cur.get("logs"), dict) else {}
        cur_ips = set()
        if isinstance(cur_logs.get("data"), dict):
            cur_ips = set((cur_logs["data"].get("ips") or []) if isinstance(cur_logs["data"].get("ips"), list) else [])
        prev_ips = set(prev_state.get("ips") or []) if isinstance(prev_state.get("ips"), list) else set()
        new_ips = sorted([ip for ip in (cur_ips - prev_ips) if isinstance(ip, str) and ip and ip != "0.0.0.0"])
        if new_ips and self.send_warning:
            self.add("warn", "<b>Новый IP входа</b>\n" + "\n".join([f"<code>{ip}</code>" for ip in new_ips[:10]]))

    def check_ports(self, cur: dict, prev_state: dict) -> None:
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

        cur_ports = cur.get("ports") if isinstance(cur.get("ports"), dict) else {}
        prev_ports_state = prev_state.get("ports")
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
        if (added or removed) and self.send_warning:
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
            self.add("warn", "\n".join(lines))

    def check_sudo_users(self, cur: dict, prev_state: dict) -> None:
        def sudo_set(x: dict) -> set[str]:
            data = x.get("data") if isinstance(x.get("data"), dict) else {}
            lst = data.get("sudo_users") if isinstance(data.get("sudo_users"), list) else []
            return set([str(u) for u in lst if isinstance(u, str) and u.strip()])

        cur_users = cur.get("users") if isinstance(cur.get("users"), dict) else {}
        prev_sudo = set(prev_state.get("sudo_users") or []) if isinstance(prev_state.get("sudo_users"), list) else set()
        cur_sudo = sudo_set(cur_users)
        new_sudo = sorted(cur_sudo - prev_sudo)
        if new_sudo and self.send_critical:
            self.add("crit", "<b>Новый sudo-пользователь</b>\n" + "\n".join([f"<code>{u}</code>" for u in new_sudo[:20]]))

    def check_updates(self, cur: dict, prev_state: dict) -> None:
        def upd_count(x: dict) -> int:
            data = x.get("data") if isinstance(x.get("data"), dict) else {}
            try:
                return int(data.get("count") or 0)
            except Exception:
                return 0

        cur_upd = cur.get("updates") if isinstance(cur.get("updates"), dict) else {}
        pc = int(prev_state.get("updates_count") or 0) if isinstance(prev_state.get("updates_count"), int) else 0
        cc = upd_count(cur_upd)
        if cc > 0 and pc == 0 and self.send_warning:
            pkgs = []
            data = cur_upd.get("data") if isinstance(cur_upd.get("data"), dict) else {}
            if isinstance(data.get("packages"), list):
                pkgs = [str(x) for x in data.get("packages")[:10]]
            text = f"<b>Доступны обновления</b>\n<code>{cc}</code> пакетов"
            if pkgs:
                text += "\n\n" + "\n".join([f"<code>{p}</code>" for p in pkgs])
            self.add("warn", text)

    def check_logs(self, cur: dict, prev_state: dict) -> None:
        cur_logs = cur.get("logs") if isinstance(cur.get("logs"), dict) else {}
        cur_log_status = str(cur_logs.get("status") or "")
        prev_log_status = str(prev_state.get("logs_status") or "")
        if cur_log_status in {"warn", "crit"}:
            data = cur_logs.get("data") if isinstance(cur_logs.get("data"), dict) else {}
            ft = int(data.get("failed_total") or 0) if isinstance(data.get("failed_total"), int) else 0
            fr = int(data.get("failed_root") or 0) if isinstance(data.get("failed_root"), int) else 0
            iu = int(data.get("invalid_user") or 0) if isinstance(data.get("invalid_user"), int) else 0
            if cur_log_status != prev_log_status:
                if cur_log_status == "crit" and self.send_critical:
                    self.add("crit", f"<b>Критичные события в логах</b>\nfailed_total=<code>{ft}</code> failed_root=<code>{fr}</code> invalid_user=<code>{iu}</code>")
                if cur_log_status == "warn" and self.send_warning:
                    self.add("warn", f"<b>Предупреждения в логах</b>\nfailed_total=<code>{ft}</code> invalid_user=<code>{iu}</code>")

    def check_firewall(self, cur: dict, prev_state: dict) -> None:
        prev_fw = prev_state.get("firewall")
        cur_fw = cur.get("firewall") if isinstance(cur.get("firewall"), dict) else {}
        cur_fw_data = cur_fw.get("data") if isinstance(cur_fw.get("data"), dict) else {}
        cur_fw_enabled = cur_fw_data.get("enabled")
        cur_fw_backend = str(cur_fw_data.get("backend") or "")
        cur_fw_rules = cur_fw_data.get("rules") if isinstance(cur_fw_data.get("rules"), list) else []
        cur_fw_rules_s = sorted([str(x) for x in cur_fw_rules if isinstance(x, str)])
        prev_fw_enabled = None
        prev_fw_rules_s: list[str] = []
        prev_fw_backend = ""
        if isinstance(prev_fw, dict):
            prev_fw_enabled = prev_fw.get("enabled")
            prev_fw_backend = str(prev_fw.get("backend") or "")
            if isinstance(prev_fw.get("rules"), list):
                prev_fw_rules_s = sorted([str(x) for x in prev_fw.get("rules") if isinstance(x, str)])

        if prev_fw_enabled is not None and cur_fw_enabled is not None:
            if prev_fw_enabled is True and cur_fw_enabled is False and self.send_critical:
                self.add("crit", f"<b>Firewall отключён</b>\nbackend=<code>{cur_fw_backend or prev_fw_backend}</code>")
            if prev_fw_enabled is False and cur_fw_enabled is True and self.send_warning:
                self.add("warn", f"<b>Firewall включён</b>\nbackend=<code>{cur_fw_backend or prev_fw_backend}</code>")

        if cur_fw_rules_s and prev_fw_rules_s != cur_fw_rules_s and self.send_warning:
            a = set(cur_fw_rules_s) - set(prev_fw_rules_s)
            r = set(prev_fw_rules_s) - set(cur_fw_rules_s)
            if a or r:
                lines: list[str] = ["<b>Изменились правила firewall</b>"]
                if a:
                    lines.append("")
                    lines.append("<b>Добавлено</b>")
                    for x in sorted(a)[:20]:
                        lines.append(f"<code>{x}</code>")
                if r:
                    lines.append("")
                    lines.append("<b>Удалено</b>")
                    for x in sorted(r)[:20]:
                        lines.append(f"<code>{x}</code>")
                self.add("warn", "\n".join(lines))

    def build_next_state(self, cur: dict) -> dict:
        cur_logs = cur.get("logs") if isinstance(cur.get("logs"), dict) else {}
        cur_ips = set()
        if isinstance(cur_logs.get("data"), dict):
            cur_ips = set((cur_logs["data"].get("ips") or []) if isinstance(cur_logs["data"].get("ips"), list) else [])

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

        cur_ports = cur.get("ports") if isinstance(cur.get("ports"), dict) else {}
        cur_ps = port_set(cur_ports)

        def sudo_set(x: dict) -> set[str]:
            data = x.get("data") if isinstance(x.get("data"), dict) else {}
            lst = data.get("sudo_users") if isinstance(data.get("sudo_users"), list) else []
            return set([str(u) for u in lst if isinstance(u, str) and u.strip()])

        cur_users = cur.get("users") if isinstance(cur.get("users"), dict) else {}
        cur_sudo = sudo_set(cur_users)

        def upd_count(x: dict) -> int:
            data = x.get("data") if isinstance(x.get("data"), dict) else {}
            try:
                return int(data.get("count") or 0)
            except Exception:
                return 0

        cur_upd = cur.get("updates") if isinstance(cur.get("updates"), dict) else {}
        cc = upd_count(cur_upd)

        cur_log_status = str(cur_logs.get("status") or "")

        cur_fw = cur.get("firewall") if isinstance(cur.get("firewall"), dict) else {}
        cur_fw_data = cur_fw.get("data") if isinstance(cur_fw.get("data"), dict) else {}
        cur_fw_enabled = cur_fw_data.get("enabled")
        cur_fw_backend = str(cur_fw_data.get("backend") or "")
        cur_fw_rules = cur_fw_data.get("rules") if isinstance(cur_fw_data.get("rules"), list) else []
        cur_fw_rules_s = sorted([str(x) for x in cur_fw_rules if isinstance(x, str)])

        return {
            "ips": sorted([ip for ip in cur_ips if isinstance(ip, str)]),
            "ports": sorted([list(x) for x in cur_ps]),
            "sudo_users": sorted([u for u in cur_sudo if isinstance(u, str)]),
            "updates_count": cc,
            "logs_status": cur_log_status,
            "firewall": {
                "backend": cur_fw_backend,
                "enabled": cur_fw_enabled,
                "rules": cur_fw_rules_s[:200],
            },
        }

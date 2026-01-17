#!/usr/bin/env bash
set -euo pipefail

APP_NAME="secops-buddy"

echo "[*] Installing ${APP_NAME}..."

if [[ $EUID -ne 0 ]]; then
  echo "[-] Please run as root (sudo ./install.sh)"
  exit 1
fi

if command -v apt-get >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y python3 python3-pip iproute2 curl
fi

mkdir -p /etc/secops-buddy
mkdir -p /var/lib/secops-buddy/snapshots
mkdir -p /var/lib/secops-buddy/diffs
touch /var/log/secops-buddy.log

if [[ ! -f /etc/secops-buddy/config.yml ]]; then
  cp ./config/config.example.yml /etc/secops-buddy/config.yml
  echo "[*] Created /etc/secops-buddy/config.yml (edit allowed_users)"
fi

cp ./systemd/secops-buddy.service /etc/systemd/system/secops-buddy.service
cp ./systemd/secops-buddy.timer /etc/systemd/system/secops-buddy.timer

systemctl daemon-reload
systemctl enable --now secops-buddy.timer

echo "[+] Done. Next steps:"
echo "    1) edit /etc/secops-buddy/config.yml"
echo "    2) create /etc/secops-buddy/.env with TELEGRAM_BOT_TOKEN"
echo "    3) run: systemctl start secops-buddy.service"
echo "    4) check logs: tail -n 200 /var/log/secops-buddy.log"

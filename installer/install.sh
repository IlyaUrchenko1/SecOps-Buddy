#!/usr/bin/env bash
set -euo pipefail

APP_NAME="secops-buddy"

echo "[*] Installing ${APP_NAME}..."

if [[ $EUID -ne 0 ]]; then
  echo "[-] Please run as root (sudo ./install.sh)"
  exit 1
fi

# Basic deps for Debian/Ubuntu
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y python3 python3-pip iproute2 curl
fi

# Create dirs
mkdir -p /etc/secops-buddy
mkdir -p /var/lib/secops-buddy/snapshots
mkdir -p /var/lib/secops-buddy/diffs
touch /var/log/secops-buddy.log

# Install python package (editable or simple copy)
# For now: install requirements if you add them later
# pip3 install -r requirements.txt

# Copy example config if not exists
if [[ ! -f /etc/secops-buddy/config.yml ]]; then
  cp ./config/config.example.yml /etc/secops-buddy/config.yml
  echo "[*] Created /etc/secops-buddy/config.yml (edit bot_token and allowed_users)"
fi

# Install systemd units
cp ./systemd/secops-buddy.service /etc/systemd/system/secops-buddy.service
cp ./systemd/secops-buddy.timer /etc/systemd/system/secops-buddy.timer

systemctl daemon-reload
systemctl enable --now secops-buddy.timer

echo "[+] Done. Next steps:"
echo "    1) edit /etc/secops-buddy/config.yml"
echo "    2) run: systemctl start secops-buddy.service"
echo "    3) check logs: tail -n 200 /var/log/secops-buddy.log"

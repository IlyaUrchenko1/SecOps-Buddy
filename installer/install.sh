#!/usr/bin/env bash
set -euo pipefail

APP_NAME="secops-buddy"

echo "[*] Installing ${APP_NAME}..."

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_DIR}"

PRIVACY_POLICY_FILE="${PROJECT_DIR}/PRIVACY_POLICY.md"

if [[ -f "${PRIVACY_POLICY_FILE}" ]]; then
  echo ""
  echo "=========================================="
  echo "Политика конфиденциальности"
  echo "=========================================="
  echo ""
  echo "Перед установкой ${APP_NAME} необходимо ознакомиться с политикой конфиденциальности."
  echo "Файл политики: ${PRIVACY_POLICY_FILE}"
  echo ""
  read -p "Вы согласны с политикой конфиденциальности? (y/n): " -n 1 -r
  echo ""
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "[!] Установка прервана. Вы должны согласиться с политикой конфиденциальности для продолжения."
    exit 1
  fi
  echo "[+] Согласие получено. Продолжаем установку..."
  echo ""
fi

if command -v apt-get >/dev/null 2>&1; then
  if [[ ${EUID:-99999} -eq 0 ]]; then
    apt-get update -y
    apt-get install -y python3 python3-venv python3-pip iproute2 curl
  else
    echo "[*] apt-get available but not running as root; skipping system packages"
  fi
fi

python3 -m venv .venv
.venv/bin/pip install -U pip setuptools wheel
.venv/bin/pip install -r requirements.txt

mkdir -p var/secops-buddy/snapshots
mkdir -p var/secops-buddy/diffs

if [[ ! -f ".env" ]]; then
  if [[ -f ".env.example" ]]; then
    cp .env.example .env
  else
    printf "TELEGRAM_BOT_TOKEN=\nTELEGRAM_ALLOWED_USERS=\n" > .env
  fi
  chmod 600 .env || true
  echo "[*] Created .env"
fi

if [[ ! -f "config/config.yml" ]]; then
  mkdir -p config
  if [[ -f "config/config.example.yml" ]]; then
    cp config/config.example.yml config/config.yml
  else
    printf "monitor_interval_seconds: 10\nnotifications:\n  enabled: true\npaths:\n  state_dir: \"./var/secops-buddy\"\n  log_file: \"./var/secops-buddy/agent.log\"\nchecks:\n  ssh: true\n  ports: true\n  firewall: false\n  users: false\n  logs: false\n  updates: false\n" > config/config.yml
  fi
  echo "[*] Created config/config.yml"
fi

echo "[+] Ready"
echo "[*] Fill files:"
echo "    .env"
echo "    config/config.yml"
echo "[*] Start:"
echo "    .venv/bin/python run.py"

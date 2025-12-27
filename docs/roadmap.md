# Roadmap — SecOps Buddy

## v1 (MVP)
- Installer + config
- systemd service + timer
- checks: ssh, ports, firewall, sudo-users, auth events, updates
- snapshots + diff
- Telegram: /status /diff /report
- алерты: CRITICAL/WARNING

## v1.1
- интеграция fail2ban (если установлен)
- фильтрация "шума" (например, игнор ephemeral ports)
- улучшенные сообщения (коротко + детали по кнопке)

## v2
- шифрованные бэкапы в S3-совместимое хранилище (restic)
- политика хранения (retention)
- алерты по бэкапам + проверка успешности

## v2.1 (Safe Actions)
- ограниченные сценарии реагирования (whitelist):
  - включить firewall
  - перезапустить fail2ban
  - закрыть заранее разрешённый порт

# Architecture — SecOps Buddy

## Компоненты
1) **Agent (secops_buddy/agent.py)**
- запускается по таймеру (systemd timer или cron)
- собирает "снимок" состояния безопасности (snapshot)
- сравнивает с предыдущим снимком (diff)
- сохраняет snapshot/diff локально

2) **Telegram Bot (secops_buddy/bot.py)**
- принимает команды /status /diff /report
- отдает последние результаты (snapshot/diff)
- доступ только по allowlist Telegram user_id

3) **Checks (secops_buddy/checks/*.py)**
- набор независимых модулей проверки (ssh/ports/firewall/users/logs/updates)
- каждый чек возвращает структурированный результат:
  - status: ok/warn/crit
  - details: кратко
  - data: сырые данные

## Поток данных
- timer → agent.run()
- agent собирает snapshot.json → сохраняет в /var/lib/secops-buddy/snapshots/
- agent строит diff относительно предыдущего → сохраняет diff.json
- agent отправляет алерты (crit/warn) в Telegram (если включено)
- bot читает последние snapshot/diff и показывает по запросу

## Принципы безопасности
- no remote shell: бот не выполняет произвольные команды
- allowlist пользователей (config.allowed_users)
- логирование действий бота
- минимальные привилегии (часть проверок требует root — это фиксируется явно)

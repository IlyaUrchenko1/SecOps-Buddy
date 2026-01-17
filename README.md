# SecOps Buddy

Linux Security Drift Monitor + Telegram-бот

## Что это

SecOps Buddy — это агент, который регулярно собирает snapshot состояния безопасности Linux-сервера, делает diff, и Telegram-бот, который показывает статус/отчёты и получает уведомления при событиях (новый IP входа, изменения портов, firewall, sudo-пользователи, обновления, warn/crit в логах).

## Возможности (v1)

- **Snapshots + Diff**: хранение `latest.json` и diff, при желании архивирование
- **Checks**: `ssh`, `ports`, `firewall` (UFW/firewalld), `users` (sudo), `logs` (auth events), `updates`
- **Telegram**: удобные команды и HTML-форматирование
- **Оповещения**: WARNING/CRITICAL по `notify_state.json` (частые проверки, не зависят от архивных snapshot)

## Требования

- Linux-сервер (Debian/Ubuntu предпочтительно)
- Python 3.12+ (достаточно `python3` + `python3-venv`)
- Для максимальной полноты данных агент лучше запускать с правами root (например: `sudo`), иначе часть проверок может быть недоступна

## Установка (полный процесс)

### 1) Скачивание

```bash
git clone <repo>
cd SecOps-Buddy
```

### 2) Подготовка окружения

```bash
bash installer/install.sh
```

Установщик:
- создаст `.venv/`
- поставит зависимости из `requirements.txt`
- создаст `.env` (если не было)
- создаст `config/config.yml` (если не было)
- создаст `var/secops-buddy/*` для состояния и логов

### 3) Заполнить конфиги

#### `.env`

- `TELEGRAM_BOT_TOKEN` — токен бота
- `TELEGRAM_ALLOWED_USERS` — список Telegram user_id через запятую (например: `123,456`)

#### `config/config.yml`

- `monitor_interval_seconds` — интервал мониторинга (например: `10`)
- `checks.*` — включение/выключение сборов
- `notifications.enabled` — включить/выключить уведомления
- `paths.state_dir` — куда писать snapshot/diff (по умолчанию `./var/secops-buddy`)

### 4) Запуск (одной командой, в фон)

Рекомендуемый запуск на сервере:

```bash
sudo .venv/bin/python run.py
```

`run.py` по умолчанию (на Linux) запускает SecOps Buddy в фоне, печатает PID, `@bot_username` (если токен валидный), и команды для логов/остановки.

Если нужен запуск без root (может быть меньше данных):

```bash
.venv/bin/python run.py
```

### 5) Остановка

```bash
kill $(cat var/secops-buddy/secops-buddy.pid)
```

### 6) Рестарт без поиска PID (флаг)

```bash
touch var/secops-buddy/restart.flag
```

## Telegram-команды

- `/start` — приветствие + меню
- `/help` — список команд
- `/status` — статус сервера и бота
- `/diff` — изменения последнего diff
- `/report` — отчёт (snapshot + diff)
- `/endpoints` — как подключиться к серверу (IP/порты/протоколы) по последнему snapshot

## Логи

Файлы (по умолчанию):

- `var/secops-buddy/run.log` — процесс run/daemon
- `var/secops-buddy/bot.log` — Telegram-бот
- `var/secops-buddy/agent.log` — агент

Просмотр:

```bash
tail -f var/secops-buddy/run.log
tail -f var/secops-buddy/bot.log
tail -f var/secops-buddy/agent.log
```

## Типовые проблемы

### Уведомления не приходят

- Проверь `.env`: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS`
- Проверь `config/config.yml`: `notifications.enabled: true`
- Проверь логи: `tail -f var/secops-buddy/bot.log` и `tail -f var/secops-buddy/agent.log`

### `/endpoints` пустой

- Нужен snapshot (сначала дождись первого прогона агента)
- Проверь, что включён `checks.ports` или `notifications.enabled` (агент собирает порты)

## Roadmap

Смотри `docs/roadmap.md`

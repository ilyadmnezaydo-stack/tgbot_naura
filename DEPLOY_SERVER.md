# Запуск на новом сервере

Ниже самый прямой путь для Linux-сервера через Docker Compose.

## Что именно поднимается

- `bot` — Telegram polling worker
- `api` — FastAPI для `GET /health` и CloudPayments webhook'ов

Важно:

- контакты и платежи CloudPayments живут в Supabase
- заметки, support, аналитика и mock-платежи живут в `data/*.json`
- в `docker-compose.yml` уже добавлен mount `./data:/app/data`, поэтому эти файлы сохраняются между пересозданиями контейнеров

## 1. Подготовить сервер

Нужны:

- Ubuntu/Debian сервер
- установленный Docker Engine
- установленный Docker Compose plugin
- доступ в интернет до Telegram API, Supabase и вашего LLM/STT endpoint

Пример для Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
```

Docker ставьте любым привычным способом. После установки проверьте:

```bash
docker --version
docker compose version
```

## 2. Забрать проект

```bash
git clone <URL_ВАШЕГО_РЕПО> bot
cd bot
mkdir -p data
```

## 3. Заполнить `.env`

```bash
cp .env.example .env
nano .env
```

Минимум, без которого бот не стартует:

```env
TELEGRAM_BOT_TOKEN=...
OWNER_USER_ID=...
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_KEY=<service_role_key>
```

Если используете CloudPayments, дополнительно заполните:

```env
CLOUDPAYMENTS_PUBLIC_ID=...
CLOUDPAYMENTS_API_SECRET=...
```

## 4. Подготовить Supabase

Нужно один раз накатить схему из файла `supabase/bot_schema.sql`.

Самый простой вариант:

1. Откройте Supabase Dashboard.
2. Перейдите в SQL Editor.
3. Выполните содержимое `supabase/bot_schema.sql`.

Альтернатива через локальный скрипт:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python scripts/apply_supabase_schema.py
```

Для этого нужен `SUPABASE_ACCESS_TOKEN` в `.env`.

## 5. Настроить AI и голос

Есть 3 рабочих сценария.

### Вариант A. Внешний OpenAI-compatible endpoint

Самый простой для сервера.

```env
LLM_BASE_URL=https://your-llm-endpoint/v1
LLM_API_KEY=...
LLM_MODEL=qwen2.5:7b

TRANSCRIPTION_REMOTE_ENABLED=true
TRANSCRIPTION_BASE_URL=https://your-stt-endpoint/v1
TRANSCRIPTION_API_KEY=...
TRANSCRIPTION_MODEL=whisper-1
TRANSCRIPTION_LOCAL_FALLBACK_ENABLED=false
```

### Вариант B. Ollama на том же сервере

Установите Ollama на хосте, затем:

```bash
ollama pull qwen2.5:7b
```

И укажите в `.env`:

```env
LLM_BASE_URL=http://host.docker.internal:11434/v1
LLM_API_KEY=local
LLM_MODEL=qwen2.5:7b
```

Если отдельного STT endpoint нет, можно оставить локальный fallback:

```env
TRANSCRIPTION_REMOTE_ENABLED=false
TRANSCRIPTION_LOCAL_FALLBACK_ENABLED=true
TRANSCRIPTION_LOCAL_MODEL=base
TRANSCRIPTION_LOCAL_DEVICE=cpu
TRANSCRIPTION_LOCAL_COMPUTE_TYPE=int8
TRANSCRIPTION_LOCAL_CPU_THREADS=4
```

Важно:

- локальная расшифровка голоса заметно грузит CPU
- при первом использовании `faster-whisper` скачает модель

### Вариант C. Вообще без голосовых фич

Если голос пока не нужен:

```env
TRANSCRIPTION_REMOTE_ENABLED=false
TRANSCRIPTION_LOCAL_FALLBACK_ENABLED=false
```

Тогда текстовый бот, поиск, контакты и напоминания будут работать, а голосовые функции будут недоступны.

## 6. Запустить контейнеры

```bash
docker compose up -d --build
```

Проверка:

```bash
docker compose ps
docker compose logs -f bot
curl http://127.0.0.1:8082/health
```

Если все хорошо, `/health` должен вернуть:

```json
{"status":"ok"}
```

## 7. Если нужны CloudPayments webhooks

Тогда `api` должен быть доступен снаружи по HTTPS.

Нужны:

- домен
- reverse proxy, например Nginx
- TLS сертификат

Проксировать нужно на локальный порт `8082`, если в `.env` не меняли `API_HOST_PORT`.

Webhook URL'ы будут такими:

- `https://<ваш-домен>/webhooks/cloudpayments/check`
- `https://<ваш-домен>/webhooks/cloudpayments/pay`
- `https://<ваш-домен>/webhooks/cloudpayments/fail`

Если CloudPayments не используется, `api` можно держать закрытым во внутренней сети.

## 8. Полезные команды

Перезапуск:

```bash
docker compose restart
```

Обновить код и пересобрать:

```bash
git pull
docker compose up -d --build
```

Посмотреть логи:

```bash
docker compose logs -f bot
docker compose logs -f api
```

Остановить:

```bash
docker compose down
```

## Частые проблемы

### Бот не стартует сразу

Смотрите:

```bash
docker compose logs -f bot
```

Обычно причина в одном из пунктов:

- не заполнен `TELEGRAM_BOT_TOKEN`
- не создана схема в Supabase
- неверный `SUPABASE_KEY`
- недоступен `LLM_BASE_URL`

### Голос не работает

Проверьте одно из двух:

- либо настроен `TRANSCRIPTION_BASE_URL`
- либо включен `TRANSCRIPTION_LOCAL_FALLBACK_ENABLED=true`

### После пересборки пропали заметки/support/аналитика

Эти данные живут в `./data` на сервере. Убедитесь, что запускаете compose из корня проекта и не удалили папку `data`.

## Рекомендуемый минимум для первого запуска

Если хочется просто быстро поднять рабочую версию:

1. Настройте Supabase.
2. Заполните `TELEGRAM_BOT_TOKEN`, `OWNER_USER_ID`, `SUPABASE_URL`, `SUPABASE_KEY`.
3. Подключите внешний LLM endpoint или локальный Ollama.
4. Временно отключите голос, если не нужен на старте.
5. Выполните `docker compose up -d --build`.

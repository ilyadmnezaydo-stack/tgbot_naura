# Naura TG Bot

[@we_aura_v2_bot](https://t.me/we_aura_v2_bot)

Naura is a Telegram bot for maintaining warm relationships with people who matter: friends, colleagues, founders, investors, clients, and anyone you want to keep in your active circle.

The bot combines a lightweight personal CRM, reminders, contact notes, voice input, and AI-assisted search so you can quickly answer queries like:

- "покажи тех, кто занимается бизнесом в Москве"
- "есть ли у меня кто-то из стартапов"
- "найди людей, с кем мы обсуждали продажи"

## What The Product Does

- Saves contacts from `@username`, forwarded messages, or quick text input.
- Stores context, tags, and reminder cadence for every person.
- Lets you mark that a contact happened and add a short note right after the conversation.
- Supports voice input for both search and notes.
- Uses AI to understand natural-language queries, not just exact tag matches.
- Shows owner analytics, support activity, notes coverage, and donation metrics.

## Current Feature Set

### Contact Management

- Add a person via `@username` or `@username короткий контекст`
- Import a contact from a forwarded Telegram message
- Edit description, tags, reminders, and status
- Pause or delete a contact card

### Reminders

- Daily, weekly, biweekly, monthly
- Custom interval in days
- One-time reminder by date
- Morning and evening reminder jobs
- Weekly owner stats job

### AI And Search

- Hybrid search: tags -> text context -> AI semantic ranking
- Semantic search across:
  - contact description
  - display name
  - tags
  - saved notes
- Smarter tag inference for concepts like startup, business, Moscow, marketing, product, investments
- Voice query routing: speech -> text -> AI intent detection -> contact search

### Notes

- Save short post-contact notes
- Add notes by text or voice
- Browse notes by date range and sort order
- Show latest note inside a contact card

### Payments And Support

- Telegram Stars donations
- CloudPayments webhook API for SBP flows
- AI-first support intake with human escalation to admins
- Owner-only analytics dashboard

### Voice Input

- Speech-to-text via OpenAI-compatible transcription endpoint
- Local fallback transcription through `faster-whisper`
- Voice search and voice notes are both supported
- Trial/subscription access flow for voice input is present

Note:
The voice subscription payment flow is currently mocked in-app, while donation and CloudPayments support are implemented separately.

## Stack

- Python 3.11
- `python-telegram-bot`
- FastAPI + Uvicorn
- Supabase
- `pydantic-settings`
- `requests` / `httpx`
- `faster-whisper`
- OpenAI-compatible LLM backend

Tested AI setup:

- Ollama
- `qwen2.5:7b` for understanding and semantic search
- local `faster-whisper` fallback for speech transcription

## Architecture

The repository contains two runtime modes:

- `bot` — Telegram polling worker
- `api` — FastAPI service for health checks and CloudPayments webhooks

`docker-compose.yml` starts both containers from the same image and switches behavior through `APP_MODE`.

## Quick Start

### 1. Clone And Install

```bash
git clone https://github.com/ilyadmnezaydo-stack/tgbot_naura.git
cd tgbot_naura
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env` and fill in the required variables.

PowerShell:

```powershell
Copy-Item .env.example .env
```

Minimal required variables:

- `TELEGRAM_BOT_TOKEN`
- `SUPABASE_URL`
- `SUPABASE_KEY`
- `OWNER_USER_ID`

Recommended AI variables:

- `LLM_BASE_URL`
- `LLM_API_KEY`
- `LLM_MODEL`

For transcription:

- `TRANSCRIPTION_REMOTE_ENABLED`
- `TRANSCRIPTION_BASE_URL`
- `TRANSCRIPTION_MODEL`

If no remote transcription endpoint is available, local fallback can still work through:

- `TRANSCRIPTION_LOCAL_FALLBACK_ENABLED=true`
- `TRANSCRIPTION_LOCAL_MODEL=base`

## Local Run

Run the Telegram bot:

```bash
python src/main.py
```

Run the webhook API:

```bash
uvicorn src.api.main:app --host 0.0.0.0 --port 8080
```

Health endpoint:

```text
GET /health
```

CloudPayments endpoints:

```text
POST /webhooks/cloudpayments/check
POST /webhooks/cloudpayments/pay
POST /webhooks/cloudpayments/fail
```

## Docker Run

### Start Bot + API

```bash
docker compose up -d --build
```

By default:

- bot runs in polling mode
- API is published on `http://127.0.0.1:8082`

Check API health:

```bash
curl http://127.0.0.1:8082/health
```

### If You Use Ollama On The Host Machine

For Docker on Windows, the bot can talk to Ollama on the host through:

```env
LLM_BASE_URL=http://host.docker.internal:11436/v1
```

The repo already contains a helper script for a stable CPU-only Ollama run on Windows:

```cmd
start_ollama_cpu.cmd
```

This starts Ollama on:

```text
127.0.0.1:11436
```

Recommended when you want a reliable local setup for:

- `qwen2.5:7b`
- semantic contact search
- voice query interpretation

## AI Setup Notes

The bot is written against an OpenAI-compatible interface, so you can plug in:

- Ollama
- OpenAI-compatible gateways
- local or remote Whisper-compatible transcription endpoints

The product works best when:

- `LLM_MODEL=qwen2.5:7b`
- transcription has either a working remote endpoint or local `faster-whisper`

## Main User Flows

### Add Contact

- Press the add button in Telegram
- Send `@username`
- Or send `@username контекст`
- Or forward a message from that person

### Search

Examples:

- `маркетинг`
- `люди из стартапов`
- `бизнес в москве`
- `найди тех, с кем обсуждали продажи`

### After Contact

- Open the contact card
- Mark that contact happened
- Add a quick note by text or voice

## Slash Commands

The bot is keyboard-first, but these technical commands exist:

- `/start`
- `/donate`
- `/paysupport`
- `/owner`

Most user navigation is intentionally done through reply and inline keyboards rather than slash commands.

## Environment Variables

Key variables from `.env.example`:

| Variable | Purpose |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `OWNER_USER_ID` | Owner access for dashboard/admin actions |
| `ADMIN_USER_IDS` | Support/admin recipients |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase service role key |
| `SUPABASE_ACCESS_TOKEN` | Supabase management PAT |
| `API_HOST_PORT` | Host port for FastAPI container |
| `LLM_BASE_URL` | OpenAI-compatible chat endpoint base |
| `LLM_API_KEY` | LLM API key |
| `LLM_MODEL` | Model used for parsing/search |
| `TRANSCRIPTION_REMOTE_ENABLED` | Enable remote STT endpoint |
| `TRANSCRIPTION_BASE_URL` | Base URL for transcription API |
| `TRANSCRIPTION_MODEL` | STT model name |
| `TRANSCRIPTION_LOCAL_FALLBACK_ENABLED` | Enable local `faster-whisper` fallback |
| `CLOUDPAYMENTS_PUBLIC_ID` | CloudPayments public key |
| `CLOUDPAYMENTS_API_SECRET` | CloudPayments webhook/API secret |

## Tests

Run all tests:

```bash
python -m unittest discover -s tests
```

The repository includes coverage for:

- search logic
- voice routing
- AI guardrails
- notes
- payments
- analytics helpers
- CloudPayments webhook handling

## Project Structure

```text
src/
  api/                FastAPI webhook service
  bot/                Telegram app, handlers, keyboards, messages
  db/                 Supabase engine and repositories
  scheduler/          Reminder and stats jobs
  services/           AI, speech, payments, support, notes, analytics
tests/                Unit and integration-style tests
data/                 Local JSON stores for notes, analytics, support, mocked billing
```

## Honest Status

What is already solid:

- contact CRUD
- reminders
- notes
- hybrid search
- voice search
- owner dashboard
- Dockerized bot + API

What still deserves future polishing:

- production billing for voice subscriptions
- richer onboarding and admin docs
- deployment automation
- deeper observability and logs aggregation

## Repository

GitHub:

[`ilyadmnezaydo-stack/tgbot_naura`](https://github.com/ilyadmnezaydo-stack/tgbot_naura)

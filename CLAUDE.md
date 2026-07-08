# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Autobots is an automation-agency codebase for WhatsApp lead filtering, CRM organization, and human handoff for local businesses in Paraguay. It grew out of two pieces of legacy code — a Google Maps lead-generation pipeline and a previous WhatsApp/n8n automation — and is being turned into a repeatable "Automation as a Service" system.

The end-to-end flow: lead sources → lead processing/scoring → manual outreach links → WhatsApp conversations → **message buffer service** → **n8n workflow** (AI response + CRM update + Telegram handoff) → human follow-up.

## Development boundaries (important)

This repo prepares, routes, buffers, and documents automation flows. It **does not send outbound WhatsApp campaigns from Python**. Treat these as needing explicit production review before doing them: sending WhatsApp replies, importing n8n workflows into a live account, wiring real Telegram/Notion/AI/Evolution credentials, or processing real customer data. Safe in-repo actions: generating manual WhatsApp links, inspecting leads locally, buffering inbound messages, forwarding combined messages to n8n, and formatting handoff alerts.

## Commands

All Python code lives under `src/` and is imported as the `autobots.*` package, so `PYTHONPATH=src` is required for every invocation.

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium   # only needed for scrapers
cp .env.example .env

# Tests (pytest with pytest-asyncio; pyproject.toml sets pythonpath=src)
pytest
pytest tests/test_message_buffer_combine.py            # single file
pytest tests/test_message_buffer_combine.py::test_name  # single test

# Lint (ruff, config in pyproject.toml; CI enforces it)
ruff check src tests

# Makefile shortcuts: make help | test | lint | buffer | report | stack

# Run the message buffer service (FastAPI)
PYTHONPATH=src uvicorn autobots.services.message_buffer.app:app --host 0.0.0.0 --port 8081 --reload

# Legacy lead pipeline
PYTHONPATH=src python -m autobots.leads.pipeline

# Legacy Flask dashboard
DASHBOARD_PASSWORD=some-local-password PYTHONPATH=src python -m autobots.dashboard.app

# Generate manual WhatsApp links from a JSON lead export
PYTHONPATH=src python -m autobots.outreach.message_generator

# Spanish pilot report from buffer-service metrics (day-7 client review)
PYTHONPATH=src python -m autobots.reporting.pilot_report --instance cliente-main --days 7

# Full local stack (postgres, redis, evolution-api, n8n, message-buffer)
docker compose up
```

## Repository layout conventions

`docs/REPO-MAP.md` explains every directory and why it exists. Several directories are deliberately **gitignored** because they hold private business or personal material; they exist locally but never reach GitHub:

- `docs/business/` — pricing, sales scripts, launch plans (private strategy).
- `docs/handbook/` — Nicolás's personal Spanish reading room; `docs/handbook/personal/` holds personal documents (career plans, reports) that are not engineering guidance.
- `prompts/` — per-niche AI agent prompts used when cloning n8n workflows for clients.
- `data/templates/` — sales/CRM template files.
- `n8n/exports/` — raw exports from the live n8n (contain workflow IDs/operational metadata); only sanitized templates are tracked under `n8n/workflows/`.

Do not track these paths, and do not move private material out of them into tracked locations.

## Architecture

### Message buffer service — `src/autobots/services/message_buffer/`
A standalone FastAPI service, the core of the live system. It receives Evolution API webhook events at `POST /webhook/evolution`, buffers short WhatsApp message fragments per sender in Redis, waits for a quiet window, then combines and forwards a single payload to n8n. It never sends WhatsApp replies itself.

Key pieces:
- `app.py` — FastAPI app; the `lifespan` wires a `RedisMessageStore`, `N8NClient`, `AudioTranscriptionService`, and a background `DebounceWorker` task.
- `debouncer.py` — `DebounceWorker` polls Redis for sessions whose debounce window (`MESSAGE_BUFFER_SECONDS`) has expired and flushes them.
- `redis_store.py` — per-sender message storage + dedup.
- `models.py` — `EvolutionWebhookParser` and `combine_buffered_messages` (message-combining logic).
- `n8n_client.py` / `retry.py` — outbound forwarding and backoff math.
- `redelivery.py` — `RedeliveryWorker` retries dead-lettered payloads (Redis DLQ: `dlq:pending` zset + `dlq:entry:*`) with exponential backoff until `DLQ_MAX_ATTEMPTS`.
- `metrics.py` — `MetricsRecorder`, per-instance daily/hourly Redis counters (fire-and-forget; must never break the pipeline). Read by `/admin/stats` and `autobots.reporting.pilot_report`.
- `transcription.py` / `audio.py` — optional voice-note transcription (off by default, `TRANSCRIPTION_PROVIDER=disabled`).
- Webhook auth uses HMAC secrets (`EVOLUTION_BUFFER_WEBHOOK_SECRET` inbound, `N8N_BUFFERED_WEBHOOK_SECRET` outbound). The `/admin/*` endpoints require `ADMIN_API_TOKEN` via the `X-Autobots-Admin-Token` header and fail closed (503) when unset.

### Legacy lead pipeline — `src/autobots/leads/`, `scrapers/`, `outreach/`
- `scrapers/` — Google Maps (`google_maps.py`) and Properstar (`properstar_agents.py`) lead discovery (Playwright).
- `leads/pipeline.py` — orchestrates cleaning (`cleaner.py`) → scoring (`scorer.py`, a weighted 0–100 purchase score) → SQLite output under `data/processed/`. Reads legacy data from `data/legacy/`.
- `outreach/` — `whatsapp_links.py` builds `wa.me` links; `message_generator.py` produces outreach messages.
- `handoff/telegram_templates.py` — formats human-handoff alert messages.
- `dashboard/` — preserved local Flask dashboard for lead review (auth via `DASHBOARD_*` env vars).

### Config
- `src/autobots/config/settings.py` — general project settings.
- `src/autobots/services/message_buffer/config.py` — `MessageBufferSettings` (pydantic-settings), loaded via `get_settings()`. All runtime config comes from environment variables; see `.env.example` for the full list.

### n8n workflows — `n8n/workflows/`
Sanitized, importable n8n workflow JSON templates (e.g. `whatsapp_buffered_inbound_template.json`) that consume the buffer service's forwarded payloads. Raw exports from a live n8n go to the gitignored `n8n/exports/`. Do not import templates into a live account without review; audit any new/modified workflow JSON with the `n8n-workflow-audit` skill.

## Docs
`docs/REPO-MAP.md` is the index of the whole repository. Architecture and deployment notes live in `docs/` — notably `docs/architecture/message-buffer-and-ai-flow.md`, `docs/architecture/conversation_memory.md`, and `docs/deployment/docker-local.md`. `docs/legacy/` preserves documentation from the pre-Autobots WhatsApp automation for reference only.

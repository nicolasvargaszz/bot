# Repository map

What every directory is, why it exists, and whether it is tracked on GitHub or deliberately kept local. If you are wondering "why is this file here?", this is the answer sheet. When adding something new, use [Where does a new file go?](#where-does-a-new-file-go) at the bottom.

## The one-paragraph story

Autobots turns WhatsApp inquiries for local businesses in Paraguay into qualified, CRM-tracked leads with human handoff. Inbound messages hit the Evolution API, get buffered and combined by a FastAPI service (`src/autobots/services/message_buffer/`), and are forwarded once per conversation burst to an n8n workflow (`n8n/workflows/`) that classifies intent, updates Notion, alerts a human on Telegram when the lead is hot, and answers on WhatsApp. Everything else in the repo either finds customers for that service (scrapers, lead scoring, outreach links) or documents how to sell, deploy, and operate it.

## Tracked directories (public, on GitHub)

### `src/autobots/` — all Python code

Imported as the `autobots.*` package; every command needs `PYTHONPATH=src`.

| Path | What it is | Why it exists |
|---|---|---|
| `services/message_buffer/` | FastAPI service: receives Evolution API webhooks, buffers WhatsApp message fragments per sender in Redis, forwards one combined payload to n8n. Includes a dead-letter queue with automatic redelivery, per-instance usage metrics, and a token-protected `/admin` API | The core of the live product. WhatsApp users write in short bursts; without buffering the AI answers each fragment separately |
| `reporting/` | `pilot_report.py` renders buffer-service metrics as a Spanish Markdown report | The deliverable for the day-7 pilot review call with a client |
| `scrapers/` | Playwright scrapers: Google Maps (`google_maps.py`, `leadgen_maps.py`) and Properstar (`properstar_agents.py`) | Finds the businesses we sell the service to |
| `leads/` | Cleaning (`cleaner.py`) and 0–100 scoring (`scorer.py`) of scraped leads; `pipeline.py` orchestrates into SQLite | Prioritizes which businesses to contact first |
| `outreach/` | `whatsapp_links.py` builds `wa.me` links; `message_generator.py` writes outreach messages; `leadgen_report.py` summarizes scrape runs | Manual outreach only — this repo never sends outbound WhatsApp campaigns |
| `handoff/` | `telegram_templates.py` formats the human-handoff alert | Keeps alert formatting testable outside n8n |
| `dashboard/` | Legacy Flask dashboard for local lead review (Basic Auth, binds to 127.0.0.1) | Predates the Notion CRM; kept because it still works for reviewing scraped leads |
| `config/` | `settings.py` plus `categories.json` / `locations.json` | Scraper search terms and general settings |
| `utils/` | `phone.py` (Paraguayan number normalization), `files.py` | Shared helpers |

### `src/scripts/` — runnable entry points

Thin CLI wrappers (`process_leads.py`, `scrape_properstar_agents.py`) around the package code. They exist so cron jobs and one-off runs don't import internals directly.

### `n8n/` — workflow templates

- `workflows/` — **sanitized, tracked templates**: the flagship `whatsapp_buffered_inbound_template.json` (classification → Notion CRM → Telegram handoff → AI reply → anti-repetition → send), plus `workflow_error_handler.json` and `workflow_monitor_sesion.json`. All secrets come from `$env.*`.
- `workflows/legacy/` — the original single-workflow proof of concept, superseded; kept as historical context.
- `exports/` — **gitignored**: raw exports from the live n8n instance (they contain workflow IDs, credential names, chat IDs). Named `YYYY-MM-DD-live-<workflow>.json`. See `n8n/README.md` for the promotion procedure.

### `tests/` — pytest suite

Covers message combining, dedup, retry, transcription, webhook security, phone/link building, lead pipeline pieces, and Telegram templates. Run with `PYTHONPATH=src pytest`. CI runs this on every push.

### `docs/` — documentation

| Path | What lives there |
|---|---|
| `architecture/` | Design notes: `overview.md` (start here), buffer + AI flow, conversation memory, error handling, Telegram handoff, voice-to-text |
| `deployment/` | `docker-local.md` (full local stack) and `digitalocean.md` (production droplet, SSH-only) |
| `operations/` | `client-onboarding.md` — signed pilot → live in one day |
| `n8n/` | `whatsapp_buffered_inbound_workflow.md` — node-by-node source of truth for the flagship workflow |
| `dashboard.md` | Legacy Flask dashboard notes |
| `legacy/` | Docs preserved from the pre-Autobots WhatsApp automation (Evolution API notes, old prompts). Reference only — review before reusing anything |
| `business/`, `handbook/` | **Gitignored** — see below |

### `web/` — landing page

Static vanilla HTML/CSS/JS (no build step). Deployed to GitHub Pages by `.github/workflows/pages.yml` on every push to `main`.

### `data/` — datasets (mostly gitignored)

Only `data/README.md` and `.gitkeep` files are tracked. `raw/` holds scraper output, `processed/` holds pipeline output (SQLite + summaries), `legacy/` holds the pre-Autobots dataset, `templates/` holds private sales/CRM template files.

### Root files

| File | Why it's there |
|---|---|
| `README.md` | Portfolio case study + quickstart |
| `CLAUDE.md` | Instructions for AI-assisted development in this repo |
| `docker-compose.yml` | Full local stack: Postgres, Redis, Evolution API, n8n, message buffer |
| `Dockerfile.message-buffer` | Image for the buffer service |
| `requirements.txt` | Python dependencies |
| `pyproject.toml` | pytest config (`pythonpath=src`) and ruff lint rules |
| `Makefile` | Shortcuts: `make test`, `make lint`, `make buffer`, `make report`, `make stack` |
| `.env.example` | Every environment variable the system reads, documented |
| `LICENSE` | MIT |
| `.github/workflows/` | `ci.yml` (pytest) and `pages.yml` (landing deploy) |
| `.claude/skills/` | `n8n-workflow-audit` — checklist + scanner run before committing any workflow JSON |

## Local-only directories (gitignored on purpose)

These exist on Nicolás's machine but never reach GitHub. They are listed in `.gitignore` with comments. **Do not move their contents into tracked paths.**

| Path | Contents | Why private |
|---|---|---|
| `docs/business/` | Pricing, sales scripts, niche analysis, marketplace ads, launch plans, risk register | Competitive strategy |
| `docs/handbook/` | Personal Spanish reading room: guides, session reports, scraped-lead reviews; `personal/` holds career documents | Personal notes and real lead data |
| `prompts/` | Per-niche AI agent prompts (real estate, retail, clinic, beauty salon) used when cloning workflows for clients | Part of the paid service |
| `data/templates/` | Sales/CRM template files (lead statuses, pricing packages, ad copy) | Business assets |
| `data/raw/`, `data/processed/`, `data/legacy/` | Scraped leads and pipeline output | Real people's contact data |
| `n8n/exports/` | Raw live n8n exports | Operational metadata (IDs, credential names) |
| `.env` | Real secrets | Obvious |

## Where does a new file go?

- **Python code** → `src/autobots/<area>/`; a runnable entry point → `src/scripts/`.
- **A test** → `tests/test_<module>.py`.
- **A sanitized n8n workflow** → `n8n/workflows/` (run the `n8n-workflow-audit` skill first). A raw live export → `n8n/exports/`.
- **Public documentation** → the matching `docs/` subfolder (`architecture/`, `deployment/`, `operations/`, `n8n/`).
- **Sales/pricing/strategy material** → `docs/business/` (stays local).
- **Personal notes or reports** → `docs/handbook/` (stays local).
- **Client agent prompts** → `prompts/` (stays local).
- **Scraped or processed data** → `data/raw/` or `data/processed/` (stays local).
- **Secrets** → `.env`, and document the variable name in `.env.example`.

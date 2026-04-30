<<<<<<< HEAD
# bots 
=======
# Autobots

Autobots is an automation agency codebase for WhatsApp lead filtering, CRM organization, and human handoff systems for local businesses in Paraguay.

## Core idea

The idea is a WhatsApp Lead Filter + CRM + Telegram/WhatsApp Human Handoff system.

It should help a business:

- answer repetitive WhatsApp questions faster
- qualify leads with useful questions
- save lead data in a simple CRM
- notify the owner or salesperson when a lead is worth follow-up
- keep humans in control of closing conversations

## Target Niches


The first target niche is real estate. See `docs/business/niches.md`.

## Repository Layout

- `src/autobots/scrapers/` - Google Maps and lead discovery tools
- `src/autobots/leads/` - lead scoring and pipeline scripts
- `src/autobots/outreach/` - manual outreach helpers, including WhatsApp links
- `src/autobots/dashboard/` - preserved local Flask dashboard
- `src/autobots/config/` - non-secret scraper settings and search config
- `n8n/workflows/` - reusable n8n workflow exports from the previous WhatsApp automation
- `docs/context/` - legacy technical context and implementation notes
- `data/legacy/` - preserved legacy scraped dataset
- `data/raw/` and `data/processed/` - local generated outputs

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env
```

Run the legacy lead pipeline:

```bash
PYTHONPATH=src python -m autobots.leads.pipeline
```

Run the legacy dashboard:

```bash
PYTHONPATH=src python -m autobots.dashboard.app
```

Generate manual WhatsApp links from a JSON lead export:

```bash
PYTHONPATH=src python -m autobots.outreach.message_generator
```

## Reusable Legacy Context

The repo preserves previous work in two groups:

- Google Maps scraping and sales pipeline logic from the old lead generation project.
- n8n, Evolution API, Telegram, Notion, and AI workflow context from the previous WhatsApp responder project, but now i have total control over the code and does not need to be private.



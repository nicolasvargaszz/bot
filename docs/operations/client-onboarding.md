# Client onboarding runbook

Repeatable procedure to take a new client from signed pilot to live WhatsApp automation. One client = one droplet stack (Evolution API + buffer + n8n + Redis + Postgres), deployed as described in the [DigitalOcean guide](../deployment/digitalocean.md). Target: live within one working day.

## 0. Prerequisites (once per client)

- Signed pilot agreement and setup fee received.
- A dedicated WhatsApp number for the business (the client's existing number works; pairing does not take the phone over, but replies will come from this number).
- Your Azure OpenAI resource (or a Gemini API key) with available quota.

## 1. Intake — collect before touching anything technical

Ask the client for:

| Asset | Why |
|---|---|
| Top 10–15 repeated questions, with the answers they actually give | Becomes the FAQ block of the agent prompt |
| Price list / service list (photo of a board is fine) | The agent must never invent prices |
| Business hours, address, delivery/coverage zones | Most common questions in every niche |
| Tone: how they greet, "vos/usted", emojis or not | The reply prompt mirrors it |
| Who receives handoff alerts (name + Telegram) | Telegram alert recipient |
| What makes a lead "hot" for them (asks price? asks for a visit?) | Tunes the handoff trigger |

## 2. Provision the stack

Follow [docs/deployment/digitalocean.md](../deployment/digitalocean.md) end to end: droplet, firewall (SSH only), clone, `.env` with fresh secrets per client (`openssl rand -hex 32` for each webhook secret and the Evolution API key), `docker compose up -d`.

Name things after the client: droplet hostname `autobots-<client>`, `EVOLUTION_INSTANCE=<client>-main`.

## 3. Prompt — adapt the niche template

Copy the closest template from the local `prompts/` directory (real estate, retail, clinic, beauty salon) and fill it with the intake answers: FAQ, prices, hours, tone, handoff criteria. Paste the result into the AI nodes of the flagship workflow (classification prompt and reply prompt).

Rules that stay in every prompt:

- Never invent prices, stock, or availability — if unknown, say a human will confirm.
- Always answer in the client's tone and in Paraguayan Spanish.
- Escalate on: meeting/visit request, price negotiation, explicit "quiero hablar con una persona", complaint.

## 4. CRM — Notion database

1. Duplicate the CRM template database in your Notion workspace (one database per client). Make sure it includes the `Human Takeover` checkbox property — ticking it on a lead silences the bot for that conversation so a human can answer.
2. Create a Notion internal integration for the client (or reuse the agency integration) and share the database with it.
3. Put `NOTION_TOKEN` and `NOTION_DATABASE_ID` in the droplet `.env`.

## 5. Handoff — Telegram

1. Create a Telegram group "Leads <Client>" with the owner and whoever answers.
2. Add the agency bot to the group; get the chat id (`https://api.telegram.org/bot<token>/getUpdates` after someone writes in the group).
3. Put `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in the droplet `.env`.

## 6. Import and wire the workflows

Through the SSH tunnel to the n8n editor:

1. Import `n8n/workflows/whatsapp_buffered_inbound_template.json`, `workflow_error_handler.json`, and `workflow_monitor_sesion.json`.
2. Every secret and ID comes from `$env` — confirm the droplet `.env` has all variables the workflows read (see `.env.example`), then restart the stack so n8n picks them up.
3. Paste the client prompt into the AI nodes (step 3).
4. Activate the three workflows.

## 7. Pair WhatsApp

Through the SSH tunnel to the Evolution manager: create the instance (`<client>-main`), show the QR to the client, they scan it from WhatsApp → Linked devices. Confirm status `open`.

## 8. Test checklist (from a phone that is not the paired one)

- [ ] Send 3 short fragments ("Hola" / "tienen X?" / "precio?") → one combined reply after the quiet window, not three replies.
- [ ] Send the same webhook twice (or a duplicated message) → no duplicated reply.
- [ ] Ask a FAQ → answer matches the client's real answer, right tone.
- [ ] Ask something off-list → agent declines to invent and offers a human.
- [ ] Ask for a meeting/price negotiation → Telegram alert arrives in the client group with context.
- [ ] Check Notion → lead exists with conversation memory fields filled.
- [ ] Send a voice note → transcribed and answered (if `TRANSCRIPTION_PROVIDER` is enabled).
- [ ] Reply twice with similar questions → responses do not repeat themselves verbatim.
- [ ] Tick `Human Takeover` on the test lead in Notion, send a message → no bot reply, lead still updated in Notion; untick → replies resume.
- [ ] Stop n8n (`docker compose stop n8n`), send a message, start n8n again → the payload is redelivered automatically from the dead-letter queue within ~30s (check `GET /admin/dlq` while n8n is down: the entry is parked there, then disappears).

## 9. Go-live and handover

- Walk the client through the Telegram alert: what it means, that *they* close the sale.
- Show them the `Human Takeover` checkbox in Notion: tick it to answer a conversation personally, untick it to hand the conversation back to the bot.
- Agree on a review call at day 7. Generate the report for it on the droplet:
  ```bash
  PYTHONPATH=src python -m autobots.reporting.pilot_report \
      --instance <client>-main --days 7 --business-hours 08-18 --output reporte.md
  ```
  It shows messages handled, instant replies, the share of inquiries arriving outside business hours, peak hours, and reliability — in Spanish, ready to read with the client. Cross-check leads captured in Notion.
- Leave the session monitor active: it alerts if the WhatsApp session drops (re-pairing takes 2 minutes with the QR).

## 10. Offboarding (if the pilot does not convert)

Delete the Evolution instance, deactivate the workflows, revoke the Notion integration share and Telegram bot from their group, destroy the droplet. The client's WhatsApp keeps working as before — the system only ever attached to it as a linked device.

# Telegram Handoff Specification

This document defines how Autobots should notify a human closer when a WhatsApp conversation needs attention.

The Telegram handoff is an alert only. It should not send WhatsApp replies by itself.

## Goal

When the AI detects that a WhatsApp lead is interested, qualified, angry, confused, asking for a person, or needs follow-up, the system should notify the owner or salesperson on Telegram with enough context to act quickly.

The alert should help the human answer one question:

```text
What should I do next with this lead?
```

## When To Trigger A Handoff

Trigger a Telegram alert when any of these conditions are true:

- The lead is qualified and interested.
- The lead asks for price.
- The lead asks for a demo.
- The lead asks to speak with a human.
- The user is angry, confused, or frustrated.
- The user should be ignored as spam.
- The lead needs follow-up but is not ready to close yet.
- The AI is unsure and human review is safer.

## Required Alert Fields

Every Telegram alert should include:

- handoff category
- lead name if available
- phone
- niche
- business/client account
- latest combined WhatsApp message
- detected intent
- lead score
- urgency
- recommended action
- suggested manual reply
- WhatsApp chat link if possible
- CRM link if available

## Handoff Categories

### 1. Hot Lead

Use when the person is qualified or close to buying.

Examples:

- Has budget and wants to continue.
- Wants to schedule a meeting or visit.
- Asked for next steps.
- Matches the ideal customer profile.

Default urgency:

```text
high
```

Default recommended action:

```text
Reply personally as soon as possible and move the conversation toward a call, demo, visit, or proposal.
```

### 2. Wants Price

Use when the person asks for cost, setup fee, monthly price, package price, property price, service price, or appointment cost.

Default urgency:

```text
medium
```

Default recommended action:

```text
Ask one or two qualifying questions before quoting, unless the correct price is already known.
```

### 3. Wants Demo

Use when the person asks to see how the system works, wants an example, or says they want a demo.

Default urgency:

```text
high
```

Default recommended action:

```text
Offer a short demo and propose a specific time.
```

### 4. Wants Human

Use when the person asks for an agent, seller, owner, doctor, receptionist, or real person.

Default urgency:

```text
high
```

Default recommended action:

```text
Take over manually and acknowledge that a person is now helping.
```

### 5. Angry / Confused User

Use when the user is upset, frustrated, distrustful, confused, or says the assistant is not helping.

Default urgency:

```text
high
```

Default recommended action:

```text
Apologize, keep the reply short, and take over manually.
```

### 6. Spam / Ignore

Use when the message is spam, offensive, irrelevant, suspicious, or clearly not a business opportunity.

Default urgency:

```text
low
```

Default recommended action:

```text
Do not reply unless manual review finds a real business reason.
```

### 7. Needs Follow-Up

Use when the person is not ready now but should be contacted again later.

Examples:

- Asked to be contacted later.
- Needs to talk to a partner.
- Wants information but did not decide yet.
- Conversation paused after showing interest.

Default urgency:

```text
medium
```

Default recommended action:

```text
Add a follow-up reminder and send a short manual message later.
```

## Telegram Message Format

Use plain text. Avoid Telegram Markdown parsing unless the message is carefully escaped.

Recommended format:

```text
[HOT LEAD]

Lead: Juan Perez
Phone: 595981123456
Niche: real_estate
Account: Autobots Demo
Intent: wants_demo
Score: 88
Urgency: high

Latest message:
Hola Nico, me interesa. Cuanto cuesta y podemos ver una demo?

Recommended action:
Offer a short demo and propose a specific time.

Suggested manual reply:
Hola Juan, buenisimo. Te puedo mostrar una demo corta hoy. Te queda bien a las 15:00?

Links:
WhatsApp: https://wa.me/595981123456
CRM: https://notion.so/example
```

## Data Contract

n8n or the AI classification step should prepare a payload like:

```json
{
  "category": "hot_lead",
  "lead_name": "Juan Perez",
  "phone": "595981123456",
  "niche": "real_estate",
  "client_account": "Autobots Demo",
  "latest_combined_message": "Hola Nico, me interesa. Cuanto cuesta?",
  "detected_intent": "wants_price",
  "lead_score": 88,
  "urgency": "high",
  "recommended_action": "Reply personally and offer a demo.",
  "suggested_manual_reply": "Hola Juan, buenisimo. Te puedo mostrar una demo corta hoy.",
  "whatsapp_link": "https://wa.me/595981123456",
  "crm_link": "https://notion.so/example"
}
```

## Field Rules

- If lead name is missing, use `Unknown`.
- If phone is missing, use `Unknown`.
- If WhatsApp link is missing but phone is available, build a `wa.me` link.
- If CRM link is missing, show `Not available`.
- Keep latest message short enough for Telegram. Truncate very long messages.
- Do not include access tokens, API keys, session IDs, or internal webhook URLs.
- Do not include sensitive documents or private medical/legal details in full.

## Suggested Manual Replies

The suggested manual reply should be short and ready to copy.

Good:

```text
Hola Juan, buenisimo. Te puedo mostrar una demo corta hoy. Te queda bien a las 15:00?
```

Too long:

```text
Hola estimado cliente, segun nuestro sistema de automatizacion con multiples integraciones...
```

## Security Notes

- Telegram alerts may contain personal data. Only send them to trusted internal chats.
- Never send credentials or internal URLs with tokens.
- Avoid logging full Telegram messages in production if they contain private user data.
- Use environment variables for Telegram bot token and chat IDs when message sending is implemented later.
- This specification only defines message templates. Sending logic should be implemented separately.


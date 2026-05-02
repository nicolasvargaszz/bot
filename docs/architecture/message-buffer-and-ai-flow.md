# Message Buffer and AI Flow Architecture

This document defines the production architecture for buffering WhatsApp messages before sending them to the AI/n8n workflow.

It is intentionally documentation-only. Before implementing code, create a focused `docs/implementation_plan.md` that breaks this architecture into small coding tasks.

## 1. Problem Explanation

WhatsApp users rarely send one complete message. They often send short fragments in sequence:

```text
Hola
Nico
Como estas?
Si me interesa tu propuesta
```

If the automation reacts to each webhook immediately, it can generate four AI responses, update the CRM four times, and send noisy handoff alerts. That feels robotic, wastes AI tokens, increases API cost, and creates a bad customer experience.

The correct behavior is to collect short messages from the same contact during a short debounce window, combine them, and process them once:

```text
Hola Nico Como estas? Si me interesa tu propuesta
```

## 2. Why Message Buffering Is Necessary

Message buffering gives the system a more human rhythm. It lets the user finish their thought before the automation responds.

Benefits:

- Prevents multiple AI replies for one user intent.
- Reduces Gemini and transcription costs.
- Makes Notion CRM updates cleaner.
- Reduces duplicate Telegram handoff alerts.
- Creates one coherent conversation event for analytics.
- Gives us a single place to handle text, audio, retries, and idempotency.

Without a buffer, n8n has to solve timing, deduplication, and message merging inside a visual workflow. That becomes fragile as clients and message volume grow.

## 3. Proposed Architecture

High-level flow:

```text
WhatsApp incoming message
  -> Evolution API webhook
  -> Message Buffer Service
  -> Redis buffer by contact/session
  -> Debounce timer 
  -> Combined text payload
  -> n8n buffered-message webhook
  -> Gemini 2.5 Flash response generation
  -> Notion CRM update
  -> Telegram handoff if needed
  -> WhatsApp response through Evolution API
```

The Message Buffer Service should be a small HTTP service owned by this repo. Its first job is not to be smart. Its job is to normalize inbound Evolution webhook events, persist them in Redis, and emit one combined payload to n8n when the debounce window is quiet.

Recommended service boundaries:

- Evolution API handles WhatsApp transport and media download endpoints.
- Message Buffer Service handles webhook normalization, Redis buffering, audio transcription dispatch, debounce, and retry to n8n.
- Redis handles temporary state, locks, timers, and retry queues.
- n8n handles AI orchestration, Notion CRM, Telegram handoff, and final WhatsApp send.
- Gemini handles response generation.
- Transcription provider handles voice-to-text behind an internal provider interface.

## 4. Redis Data Model

Use contact/session scoped keys. A session key should be stable per client instance and phone number.

Recommended session key:

```text
client:{client_id}:contact:{phone}
```

Example:

```text
client:inmobiliaria-demo:contact:595981123456
```

Suggested Redis keys:

```text
buffer:{session_key}
buffer_meta:{session_key}
debounce:{session_key}
lock:{session_key}
processed_event:{event_id}
retry:n8n
deadletter:n8n
```

### `buffer:{session_key}`

Type: Redis list.

Stores normalized message fragments in arrival order.

Each item should be JSON:

```json
{
  "event_id": "evolution-message-id",
  "type": "text",
  "text": "Hola",
  "timestamp": "2026-05-02T12:00:00Z",
  "source": "whatsapp",
  "raw_message_type": "conversation"
}
```

For audio:

```json
{
  "event_id": "evolution-audio-message-id",
  "type": "audio_transcription",
  "text": "Hola, quiero saber el precio",
  "timestamp": "2026-05-02T12:00:02Z",
  "source": "whatsapp",
  "raw_message_type": "audioMessage",
  "transcription_provider": "whisper_api",
  "transcription_status": "success"
}
```

### `buffer_meta:{session_key}`

Type: Redis hash.

Suggested fields:

```text
client_id
phone
last_event_at
first_event_at
message_count
contains_audio
last_event_id
n8n_attempts
```

### `debounce:{session_key}`

Type: string with TTL.

Stores the latest debounce token. Each new message replaces the token and resets the TTL.

Example value:

```text
2026-05-02T12:00:03Z:random-token
```

### `lock:{session_key}`

Type: string with short TTL.

Prevents two workers from flushing the same buffer at the same time.

### `processed_event:{event_id}`

Type: string with TTL.

Prevents duplicate processing if Evolution retries the same webhook.

Recommended TTL: 24 to 72 hours.

### `retry:n8n`

Type: Redis stream or list.

Stores combined payloads that failed to deliver to n8n and should be retried.

### `deadletter:n8n`

Type: Redis stream or list.

Stores payloads that failed permanently after retry exhaustion.

## 5. Message Lifecycle

1. Evolution API sends webhook to the Message Buffer Service.
2. Service validates request shape and extracts:
   - client or instance id
   - phone/contact id
   - message id
   - message type
   - text or media metadata
   - timestamp
3. Service checks `processed_event:{event_id}`.
4. If duplicate, return HTTP 200 and do nothing.
5. If text, normalize and append to `buffer:{session_key}`.
6. If audio, download/transcribe it, then append the transcription to the same buffer.
7. Service updates `buffer_meta:{session_key}`.
8. Service writes a new `debounce:{session_key}` token with TTL.
9. When the debounce window expires, the service flushes the buffer.
10. Flush worker acquires `lock:{session_key}`.
11. Worker reads fragments in order and creates `combined_text`.
12. Worker sends one payload to the n8n buffered webhook.
13. If n8n accepts the payload, worker deletes buffer and metadata.
14. If n8n fails, worker schedules retry and keeps or snapshots the payload.

Combined payload to n8n:

```json
{
  "client_id": "inmobiliaria-demo",
  "session_key": "client:inmobiliaria-demo:contact:595981123456",
  "phone": "595981123456",
  "combined_text": "Hola Nico Como estas? Si me interesa tu propuesta",
  "message_count": 4,
  "contains_audio": false,
  "event_ids": ["msg-1", "msg-2", "msg-3", "msg-4"],
  "first_event_at": "2026-05-02T12:00:00Z",
  "last_event_at": "2026-05-02T12:00:04Z"
}
```

## 6. Debounce Strategy

Start simple:

- Default debounce window: 6 seconds.
- Minimum window: 3 seconds.
- Maximum window: 12 seconds.
- Longer window for audio: 8 to 12 seconds, because transcription may take longer.

The window should reset every time a new message arrives for the same session.

Implementation options:

1. Polling worker:
   - Store `last_event_at`.
   - Worker scans active sessions.
   - Flush when `now - last_event_at >= debounce_seconds`.

2. Redis key expiration:
   - Set `debounce:{session_key}` with TTL.
   - Subscribe to Redis keyspace notifications.
   - Flush when key expires.

Recommended first implementation: polling worker.

Reason: Redis keyspace notifications require Redis configuration and can be easy to misconfigure in Docker. A polling worker is less elegant but more predictable for a first production version.

Flush rule:

```text
Flush only when:
- buffer exists
- last_event_at is older than debounce window
- no active lock exists
- there is at least one usable text fragment
```

## 7. Audio Transcription Strategy

Audio should be converted into text before entering the main AI flow.

Flow:

```text
Evolution audio webhook
  -> detect audioMessage
  -> download media using Evolution API
  -> pass audio bytes to transcription provider
  -> receive text
  -> append transcription to Redis buffer
```

Provider design:

```text
TranscriptionProvider
  -> transcribe(audio_bytes, mime_type, metadata) -> TranscriptionResult
```

The service should support provider swapping by configuration:

```text
TRANSCRIPTION_PROVIDER=whisper_api
```

Recommended provider order:

1. Start with external Whisper API or another reliable hosted transcription API.
2. Later evaluate local transcription only if cost or privacy requires it.
3. Keep the interface provider-based so local Whisper, Faster Whisper, or another provider can be added later.

Why not local first:

- Local transcription increases server CPU/RAM needs.
- DigitalOcean droplets may need larger instances.
- Audio formats from WhatsApp can require conversion.
- Operational complexity is higher than the value at MVP stage.

Audio failure behavior:

- If transcription fails, do not block the whole conversation forever.
- Add a fallback fragment:

```text
[Voice message received but transcription failed]
```

- Mark `transcription_status=failed`.
- Optionally escalate to Telegram if the user sent only audio and transcription failed.

## 8. Gemini Response Generation Strategy

n8n should receive a single combined message and call Gemini 2.5 Flash once per buffered user intent.

Recommended model:

```text
Gemini 2.5 Flash
```

Prompt responsibilities:

- Answer repetitive questions.
- Ask qualification questions.
- Detect intent and readiness.
- Return structured flags for CRM and handoff.

Preferred n8n AI output format:

```json
{
  "reply": "Claro. Estas buscando comprar o alquilar?",
  "lead_status": "qualifying",
  "should_update_crm": true,
  "should_handoff": false,
  "handoff_reason": null,
  "qualification": {
    "intent": "rent",
    "zone": null,
    "budget": null,
    "property_type": null,
    "timeline": null,
    "wants_visit": false
  }
}
```

Gemini should not directly send WhatsApp messages. n8n should validate the AI output first, then decide whether to send, update Notion, or escalate.

Guardrails:

- Keep responses short.
- Ask one or two questions at a time.
- Never claim to be the property owner unless configured.
- Never invent property availability, price, requirements, or appointment times.
- Use a human handoff when the lead is ready, angry, confused, or asks for a person.

## 9. Notion CRM Update Strategy

Notion should receive one update per buffered user intent, not one update per tiny WhatsApp fragment.

Recommended CRM object:

```text
Lead / Contact
```

Suggested fields:

```text
Phone
Name
Client
Channel
Status
Intent
Zone
Budget
Property Type
Timeline
Wants Visit
Last Message
Conversation Summary
Last Contacted At
Handoff Needed
Handoff Reason
Owner / Salesperson
```

Update strategy:

1. Search lead by phone and client id.
2. If found, update existing lead.
3. If not found, create a new lead.
4. Append or summarize latest combined message.
5. Store structured qualification fields from Gemini.
6. Set status based on qualification:
   - `new`
   - `qualifying`
   - `interested`
   - `ready_for_handoff`
   - `closed`
   - `not_qualified`

Avoid storing raw full conversation forever in Notion unless the client needs it. A concise summary is easier for salespeople.

## 10. Telegram Handoff Strategy

Telegram handoff should happen only when the conversation needs a human.

Recommended handoff triggers:

- User asks to schedule a visit.
- User provides budget, zone, and property type.
- User asks for a human/seller.
- User is angry or frustrated.
- AI confidence is low.
- Transcription failed for an audio-only message.
- User asks something the system cannot answer safely.

Telegram alert payload:

```text
New qualified WhatsApp lead

Client: Inmobiliaria Demo
Phone: +595 981 123456
Intent: Rent
Zone: Villa Morra
Budget: 3.000.000 Gs
Property: Apartment
Reason: Wants to schedule a visit

Last message:
"Quiero alquilar en Villa Morra, mi presupuesto es 3 millones. Podemos visitar?"
```

Avoid sending duplicate handoff alerts by storing a short-lived handoff key:

```text
handoff_sent:{session_key}:{lead_status}
```

Suggested TTL: 30 to 120 minutes.

## 11. Error Handling

The system should fail gracefully and avoid message loss.

Inbound webhook errors:

- Invalid payload: return 400 if clearly malformed.
- Unknown message type: return 200 and log as ignored.
- Duplicate event id: return 200.
- Redis unavailable: return 503 so Evolution can retry if configured.

Audio errors:

- Media download fails: retry download.
- Transcription fails: append fallback fragment and optionally handoff.
- Unsupported audio format: log and mark transcription failed.

n8n delivery errors:

- Timeout: retry.
- 4xx response: send to dead letter unless it is a known temporary issue.
- 5xx response: retry with backoff.

AI errors:

- n8n should send a safe fallback response or escalate.
- Do not expose stack traces or provider errors to the WhatsApp user.

Notion errors:

- Do not block WhatsApp response if Notion update fails.
- Queue CRM update retry.
- Include CRM failure in logs/alerts.

Telegram errors:

- Do not block WhatsApp response.
- Retry handoff alert.
- If Telegram repeatedly fails, log to dead letter.

## 12. Retry Strategy

Use retries where they protect the user experience, but avoid infinite loops.

Recommended retry policy:

```text
attempt 1: immediate
attempt 2: 5 seconds
attempt 3: 30 seconds
attempt 4: 2 minutes
attempt 5: 10 minutes
then dead letter
```

Retryable operations:

- Evolution media download.
- Transcription request.
- n8n webhook delivery.
- Notion update.
- Telegram handoff.

Idempotency:

- Every incoming Evolution message must use `processed_event:{event_id}`.
- Every combined n8n payload should include a deterministic `buffer_id`.
- n8n should tolerate receiving the same `buffer_id` twice.

Example buffer id:

```text
sha256(client_id + phone + first_event_id + last_event_id)
```

## 13. Security Considerations

Do not commit:

- `.env`
- Redis dumps with real conversations
- n8n credential exports
- Evolution API keys
- WhatsApp QR/session data
- Notion tokens
- Telegram bot tokens
- OpenAI/Gemini keys
- Audio files from users
- Real lead datasets

Webhook security:

- Require a shared secret header between Evolution and the buffer service.
- Require a shared secret header between buffer service and n8n.
- Reject requests without the expected header.
- Keep webhooks behind HTTPS in production.

Data privacy:

- Use short Redis TTLs for buffered messages.
- Avoid storing audio files unless required.
- Redact phone numbers in logs where practical.
- Keep production logs out of GitHub.

Docker/security:

- Do not expose Redis publicly.
- Do not expose Postgres publicly.
- Run n8n with authentication.
- Use strong `N8N_BASIC_AUTH_PASSWORD`.
- Keep Evolution API manager protected.

Public repository hygiene:

- Keep legacy campaign workflow clearly labeled as legacy context.
- Prefer sanitized demo workflows for portfolio presentation.
- Keep real client prompts, phone numbers, and CRM schemas out of public commits.

## 14. Environment Variables Needed

Message buffer service:

```env
BUFFER_SERVICE_HOST=0.0.0.0
BUFFER_SERVICE_PORT=8081
BUFFER_SHARED_SECRET=
BUFFER_DEBOUNCE_SECONDS=6
BUFFER_AUDIO_DEBOUNCE_SECONDS=10
BUFFER_MAX_MESSAGES_PER_SESSION=30
BUFFER_SESSION_TTL_SECONDS=3600
BUFFER_EVENT_ID_TTL_SECONDS=259200
```

Redis:

```env
REDIS_URL=redis://redis:6379/0
```

Evolution API:

```env
EVOLUTION_API_KEY=
EVOLUTION_SERVER_URL=http://evolution-api:8080
EVOLUTION_INSTANCE_NAME=
```

n8n:

```env
N8N_BUFFERED_WEBHOOK_URL=
N8N_BUFFERED_WEBHOOK_SECRET=
```

Transcription:

```env
TRANSCRIPTION_PROVIDER=whisper_api
OPENAI_API_KEY=
TRANSCRIPTION_TIMEOUT_SECONDS=30
TRANSCRIPTION_MAX_AUDIO_SECONDS=120
```

Gemini/n8n:

```env
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
```

Notion:

```env
NOTION_TOKEN=
NOTION_DATABASE_ID=
```

Telegram:

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

Operational:

```env
LOG_LEVEL=INFO
ENVIRONMENT=development
SENTRY_DSN=
```

## 15. Docker Services Needed

Minimum production-like stack:

```text
evolution-api
postgres
redis
n8n
message-buffer-service
```

Optional later services:

```text
worker
transcription-worker
prometheus
grafana
traefik or nginx
```

Suggested responsibilities:

- `message-buffer-service`: receives webhooks and writes Redis.
- `worker`: scans Redis for flushable buffers and retries failed deliveries.
- `redis`: stores temporary buffers, locks, idempotency keys, and retry queues.
- `n8n`: executes AI, CRM, Telegram, and WhatsApp response logic.
- `postgres`: backs Evolution API and optionally n8n.

For the first implementation, `message-buffer-service` and `worker` can run in one container if the code is cleanly separated internally.

## 16. Future Improvements

Implementation sequence:

1. Write `docs/implementation_plan.md`.
2. Stabilize lead pipeline and sanitized outputs.
3. Generate manual WhatsApp links for outreach.
4. Implement Redis message buffer service.
5. Build n8n buffered-message workflow.
6. Add audio transcription provider interface.
7. Add Notion CRM update flow.
8. Add Telegram handoff deduplication.
9. Add tests and CI.

Product improvements:

- Per-client debounce settings.
- Per-client prompt templates.
- Lead scoring inside the CRM update flow.
- Conversation summary memory.
- Handoff dashboard for owners.
- Support multiple WhatsApp instances.
- Support opt-out and compliance flags.
- Analytics: response time, lead readiness, handoff rate, conversion rate.
- Local transcription provider for privacy-sensitive clients.
- Human takeover state that pauses AI responses while a salesperson is handling the lead.

Operational improvements:

- Health check endpoint for the buffer service.
- Metrics for active buffers and flush latency.
- Dead-letter inspection command.
- Automated secret scanning in GitHub Actions.
- Staging n8n workflow separate from production workflow.
- Sanitized demo workflow for the public GitHub repo.

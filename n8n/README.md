# n8n Workflows

This folder stores reusable n8n workflow exports from the previous WhatsApp responder project.

## Workflow Map

```mermaid
flowchart TD
    A[FastAPI message buffer] --> B[whatsapp_buffered_inbound_template]
    B --> C[Intent classification]
    C --> D[Notion memory lookup]
    D --> E[Create or update lead]
    E --> F{Needs human?}
    F -- yes --> G[Telegram handoff]
    F -- no --> H[Build AI context]
    G --> H
    H --> I[AI response]
    I --> J[Anti-repeat guard]
    J --> K[Evolution API send message]
    J --> L[Notion memory update]
    M[workflow_error_handler] --> N[Admin alert]
    O[workflow_monitor_sesion] --> P[Session health checks]
```

Current workflows:

- `workflow_agente_whatsapp.json` - inbound WhatsApp agent proof of concept with handoff
- `workflow_error_handler.json` - error alert workflow
- `workflow_monitor_sesion.json` - session monitor workflow
- `whatsapp_buffered_inbound_template.json` - new buffered inbound workflow template for messages coming from the FastAPI Redis buffer service

These files are context for future business automations. Before using them for a client:

- replace political-campaign language with client-specific business language
- add fresh n8n credentials after import
- configure Evolution API and n8n through `.env`
- test with a sandbox number first
- keep human handoff enabled

Do not store n8n credentials, QR sessions, WhatsApp session data, or production execution data in this repository.
Live exports from n8n can also include workflow IDs, credential names, Telegram chat IDs, calendar account IDs, and other operational metadata. Keep those local or sanitize them before committing; use `whatsapp_buffered_inbound_template.json` as the tracked template.

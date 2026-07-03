---
name: n8n-workflow-audit
description: Audit an n8n workflow JSON export for hardcoded credentials, unresolved placeholders, missing webhook secret checks, dangling node connections, and operational metadata before committing it to the repo or importing it for a client. Use whenever a workflow JSON under n8n/workflows/ is added, exported from a live n8n, or modified.
---

# n8n Workflow Audit

Why this skill exists: every client engagement produces workflow JSON exported
from a live n8n instance, and live exports leak things a public repo must
never contain (credential IDs, instance IDs, chat IDs, pinned execution data,
keys pasted into URLs during debugging). This encodes the checklist so it is
run the same way every time.

## Run the scanner first

```bash
python .claude/skills/n8n-workflow-audit/scripts/audit_n8n_workflow.py n8n/workflows/*.json n8n/workflows/legacy/*.json
```

Exit 0 is clean. Fix every finding or explicitly justify it before committing.

## Manual checks the scanner cannot do

1. **Secrets via env only.** Every key, token, chat ID, and server URL must be
   an `{{ $env.NAME }}` expression. If a value must change per client, it is
   an env var, not an edit inside a node.
2. **Expression prefix.** n8n parameters that contain `{{ ... }}` templating
   must start with `=`. Without it the text is sent literally (this bug
   shipped once in the session-monitor alert).
3. **Both webhook hops authenticated.** Inbound webhook workflows must reject
   requests whose `X-Autobots-Webhook-Secret` header does not match
   `$env.N8N_BUFFERED_WEBHOOK_SECRET`, and must fail closed (throw) when the
   env var is unset.
4. **Error workflow wired.** Any workflow that talks to a customer must have
   the error handler selected in Settings → Error Workflow.
5. **New env vars propagated.** Any new `$env.*` reference needs a line in
   `.env.example` and in the n8n service section of `docker-compose.yml` —
   n8n containers only see variables the compose file passes through.
6. **Docs updated.** Node renames and new branches go into
   `docs/n8n/whatsapp_buffered_inbound_workflow.md` (node names there must
   match the JSON exactly).
7. **Live exports stay untracked.** Exports from a running instance keep
   workflow/version/instance IDs; commit only sanitized templates. The
   tracked template is `whatsapp_buffered_inbound_template.json`; live
   variants belong in .gitignore.

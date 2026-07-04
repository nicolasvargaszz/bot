# Deploying to DigitalOcean

This guide takes the full stack (Evolution API, message buffer, n8n, Redis, Postgres) to a single DigitalOcean droplet using the `docker-compose.yml` at the repo root. It assumes the GitHub Student Pack credit ($200), which covers roughly 16 months of the recommended droplet.

## Security model (read this first)

The droplet exposes **no public HTTP surface at all**. WhatsApp connectivity works outbound (Evolution API keeps a websocket to WhatsApp's servers), Telegram and AI calls are outbound, and every webhook hop (Evolution → buffer → n8n) stays inside the Docker network protected by shared secrets. The only open port is SSH.

Admin interfaces (n8n editor, Evolution manager) are bound to `127.0.0.1` on the droplet and reached through SSH tunnels. There is no TLS certificate, reverse proxy, or public domain to maintain, because there is nothing public to protect.

```text
Internet ──ssh (22)──▶ droplet
                        ├─ n8n editor        127.0.0.1:5678  (SSH tunnel only)
                        ├─ Evolution manager 127.0.0.1:8080  (SSH tunnel only)
                        └─ message buffer    internal Docker network only
```

## 1. Create the droplet

In the DigitalOcean control panel:

1. **Create → Droplets**.
2. Image: **Ubuntu 24.04 LTS x64**.
3. Plan: **Basic → Regular → $12/mo (2 GB RAM / 1 vCPU / 50 GB SSD)**. 1 GB is not enough for n8n + Evolution + Postgres together.
4. Region: closest to Paraguay (NYC works fine).
5. Authentication: **SSH key** (never password). Add your public key (`cat ~/.ssh/id_ed25519.pub`, generate with `ssh-keygen -t ed25519` if you have none).
6. Hostname: `autobots-prod`.

## 2. Prepare the server

SSH in as root and create a working user:

```bash
ssh root@<droplet-ip>

adduser autobots
usermod -aG sudo autobots
rsync --archive --chown=autobots:autobots ~/.ssh /home/autobots
```

Firewall — SSH only:

```bash
ufw allow OpenSSH
ufw enable
ufw status   # should list only OpenSSH
```

Swap (2 GB, keeps the droplet alive during n8n/AI spikes):

```bash
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

Docker (official convenience script installs the engine and the compose plugin):

```bash
curl -fsSL https://get.docker.com | sh
usermod -aG docker autobots
```

Log out and back in as `autobots` so the group applies:

```bash
exit
ssh autobots@<droplet-ip>
docker ps   # should work without sudo
```

## 3. Deploy the stack

```bash
git clone https://github.com/<your-user>/autobots.git
cd autobots
cp .env.example .env
```

Generate the three secrets and the Evolution API key:

```bash
for var in EVOLUTION_API_KEY EVOLUTION_POSTGRES_PASSWORD EVOLUTION_BUFFER_WEBHOOK_SECRET N8N_BUFFERED_WEBHOOK_SECRET; do
  echo "$var=$(openssl rand -hex 32)"
done
```

Edit `.env` and set, at minimum:

```env
EVOLUTION_API_KEY=<generated>
EVOLUTION_POSTGRES_PASSWORD=<generated>
EVOLUTION_BUFFER_WEBHOOK_SECRET=<generated>
N8N_BUFFERED_WEBHOOK_SECRET=<generated>
EVOLUTION_INSTANCE=autobots-main

# AI provider — Azure OpenAI on Student Pack credits:
AI_PROVIDER=azure
AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com
AZURE_OPENAI_KEY=<from Azure portal>
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_CLASSIFICATION_DEPLOYMENT=gpt-4o-mini

# CRM + handoff:
NOTION_TOKEN=<integration token>
NOTION_DATABASE_ID=<database id>
TELEGRAM_CHAT_ID=<your chat id>
```

The compose file refuses to start if a required secret is missing (`${VAR:?...}`), so a misconfigured droplet fails loudly instead of running open.

Build and start:

```bash
docker compose up -d --build
docker compose ps        # wait until postgres/redis are healthy
docker compose logs -f message-buffer   # should log startup without errors
```

## 4. Configure n8n (through the SSH tunnel)

From **your laptop**:

```bash
ssh -L 5678:127.0.0.1:5678 -L 8080:127.0.0.1:8080 autobots@<droplet-ip>
```

Open `http://localhost:5678` and create the **owner account** (this is n8n's real access control; the old basic-auth env vars are deprecated no-ops and were removed from the compose file).

Then:

1. **Credentials → Add credential → Telegram**: paste `TELEGRAM_BOT_TOKEN` from @BotFather.
2. **Import** the three files from `n8n/workflows/`: the buffered inbound template, the error handler, the session monitor.
3. Open each Telegram node once and select the credential you created.
4. In the buffered template: **Settings → Error Workflow → "Autobots - Error Handler"**.
5. **Activate** the buffered template and the session monitor.

The workflows read everything else (`AI_PROVIDER`, Azure/Gemini keys, Notion, chat IDs, Evolution URL) from the container environment you already set in `.env` — nothing to paste into nodes.

## 5. Connect WhatsApp (Evolution API)

Still with the tunnel open, create the instance:

```bash
curl -s -X POST http://localhost:8080/instance/create \
  -H "apikey: $EVOLUTION_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"instanceName": "autobots-main", "qrcode": true, "integration": "WHATSAPP-BAILEYS"}'
```

Point its webhook at the buffer **with the shared secret header** (the buffer rejects calls without it):

```bash
curl -s -X POST http://localhost:8080/webhook/set/autobots-main \
  -H "apikey: $EVOLUTION_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "webhook": {
      "enabled": true,
      "url": "http://message-buffer:8081/webhook/evolution",
      "headers": {
        "X-Autobots-Webhook-Secret": "'"$EVOLUTION_BUFFER_WEBHOOK_SECRET"'",
        "Content-Type": "application/json"
      },
      "byEvents": true,
      "events": ["MESSAGES_UPSERT"]
    }
  }'
```

Verify with `GET /webhook/find/autobots-main` (same `apikey` header). Then open `http://localhost:8080/manager`, log in with `EVOLUTION_API_KEY`, and scan the QR with the business phone.

## 6. End-to-end test

Send a WhatsApp message from another phone to the connected number, then watch it cross each hop:

```bash
docker compose logs -f message-buffer
# expect: webhook accepted -> buffered -> (debounce) -> n8n_delivery_success
```

In n8n, **Executions** should show a successful run of the buffered template; the reply arrives on WhatsApp, the lead appears in Notion, and (if the intent is hot) the Telegram handoff message fires.

If the buffer logs `401`, the webhook secret header in step 5 does not match `.env`. If n8n shows `Unauthorized webhook request`, `N8N_BUFFERED_WEBHOOK_SECRET` differs between the two containers — both read the same `.env`, so re-run `docker compose up -d` after edits.

## 7. Operations

Update the stack (images are pinned; changes are deliberate):

```bash
git pull
docker compose up -d --build
```

Back up the state that matters (n8n workflows/credentials and the WhatsApp session):

```bash
docker run --rm -v autobots_n8n_data:/data -v "$PWD":/backup alpine \
  tar czf /backup/n8n_data_$(date +%F).tar.gz -C /data .
docker compose exec postgres pg_dump -U evolution evolution > evolution_$(date +%F).sql
```

Copy backups off the droplet with `scp`. The session monitor workflow alerts on Telegram within 10 minutes if WhatsApp disconnects; reconnect by re-scanning the QR through the tunnel.

## Cost

| Item | Monthly | Covered by |
| --- | --- | --- |
| Droplet 2 GB | $12 | DO Student Pack credit ($200 ≈ 16 months) |
| Azure OpenAI (gpt-4o-mini classification + gpt-4o replies, low volume) | ~$1–5 | Azure Student credit ($100) |
| Evolution API, n8n, Redis, Postgres | $0 | self-hosted |

A realistic pilot for one client runs for months entirely on student credits.

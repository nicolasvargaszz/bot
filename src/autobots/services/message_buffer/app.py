"""FastAPI entry point for the WhatsApp message buffer service."""

from __future__ import annotations

import asyncio
import hmac
import logging
import time
from collections.abc import Mapping
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from pydantic import BaseModel

from autobots.services.message_buffer.config import get_settings
from autobots.services.message_buffer.debouncer import DebounceWorker
from autobots.services.message_buffer.logging_config import configure_logging
from autobots.services.message_buffer.metrics import MetricsRecorder
from autobots.services.message_buffer.models import EvolutionWebhookParser
from autobots.services.message_buffer.n8n_client import N8NClient
from autobots.services.message_buffer.redelivery import RedeliveryWorker
from autobots.services.message_buffer.redis_store import RedisMessageStore
from autobots.services.message_buffer.transcription import AudioTranscriptionService

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


class AppState:
    """Runtime dependencies attached to the FastAPI app."""

    store: RedisMessageStore | None = None
    metrics: MetricsRecorder | None = None
    worker: DebounceWorker | None = None
    worker_task: asyncio.Task[None] | None = None
    redelivery_worker: RedeliveryWorker | None = None
    redelivery_task: asyncio.Task[None] | None = None
    transcription_service: AudioTranscriptionService | None = None


state = AppState()


class HealthResponse(BaseModel):
    status: str
    redis: bool
    n8n_configured: bool


class ActiveBufferInfo(BaseModel):
    session_id: str
    instance: str
    phone: str
    push_name: str
    message_count: int
    seconds_since_last_event: float


class ActiveBuffersResponse(BaseModel):
    total: int
    buffers: list[ActiveBufferInfo]


class DLQEntryInfo(BaseModel):
    dlq_id: str
    instance: str
    phone: str
    attempts: int
    failed_at: str
    last_error: str
    next_attempt_at: str


class DLQResponse(BaseModel):
    total: int
    entries: list[DLQEntryInfo]


@asynccontextmanager
async def lifespan(_: FastAPI):
    state.store = RedisMessageStore.from_settings(settings)
    state.metrics = MetricsRecorder(state.store.redis, settings)
    n8n_client = N8NClient(settings)
    state.transcription_service = AudioTranscriptionService(settings)
    state.worker = DebounceWorker(state.store, n8n_client, settings, metrics=state.metrics)
    state.worker_task = asyncio.create_task(state.worker.run_forever())
    state.redelivery_worker = RedeliveryWorker(
        state.store, n8n_client, settings, metrics=state.metrics
    )
    state.redelivery_task = asyncio.create_task(state.redelivery_worker.run_forever())
    try:
        yield
    finally:
        if state.worker:
            state.worker.stop()
        if state.redelivery_worker:
            state.redelivery_worker.stop()
        if state.worker_task:
            await state.worker_task
        if state.redelivery_task:
            await state.redelivery_task
        if state.store:
            await state.store.close()


app = FastAPI(
    title="Autobots Message Buffer Service",
    description=(
        "Buffers WhatsApp message fragments from the Evolution API per sender, "
        "combines them after a quiet window, and forwards one payload to n8n. "
        "Failed forwards are parked in a dead-letter queue and redelivered "
        "automatically. Admin endpoints expose buffers, the DLQ, and per-client "
        "usage metrics."
    ),
    version="0.2.0",
    lifespan=lifespan,
)


def _verify_evolution_webhook_secret(request: Request) -> None:
    expected_secret = settings.evolution_buffer_webhook_secret.strip()
    if not expected_secret:
        logger.error("evolution_buffer_webhook_secret_missing")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook secret is not configured",
        )

    received_secret = request.headers.get(settings.webhook_secret_header, "").strip()
    if not hmac.compare_digest(received_secret, expected_secret):
        logger.warning(
            "evolution_webhook_unauthorized",
            extra={"client_host": request.client.host if request.client else ""},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized webhook request",
        )


def _verify_admin_token(request: Request) -> None:
    """Fail-closed token check for the /admin endpoints."""
    expected_token = settings.admin_api_token.strip()
    if not expected_token:
        logger.error("admin_api_token_missing")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin API token is not configured",
        )

    received_token = request.headers.get(settings.admin_token_header, "").strip()
    if not hmac.compare_digest(received_token, expected_token):
        logger.warning(
            "admin_request_unauthorized",
            extra={"client_host": request.client.host if request.client else ""},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized admin request",
        )


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health() -> HealthResponse:
    """Health check for container orchestration and local debugging."""
    redis_ok = False
    if state.store:
        try:
            redis_ok = await state.store.ping()
        except Exception:
            logger.exception("redis_health_check_failed")

    return HealthResponse(
        status="ok" if redis_ok else "degraded",
        redis=redis_ok,
        n8n_configured=bool(settings.n8n_webhook_url),
    )


@app.post("/webhook/evolution", tags=["webhook"])
async def evolution_webhook(request: Request) -> dict[str, Any]:
    """Receive Evolution API webhook events and append them to Redis buffers."""
    _verify_evolution_webhook_secret(request)

    try:
        payload = await request.json()
    except Exception as exc:
        logger.warning("evolution_webhook_invalid_json", extra={"error": str(exc)})
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    if not isinstance(payload, Mapping):
        raise HTTPException(status_code=400, detail="JSON payload must be an object")

    parsed = EvolutionWebhookParser.parse(payload)
    event_instance = str(payload.get("instance") or "unknown")
    if parsed.message:
        event_instance = parsed.message.instance
    if state.metrics:
        await state.metrics.record(event_instance, "received")

    if not parsed.accepted or not parsed.message:
        if state.metrics:
            await state.metrics.record(event_instance, "ignored")
        logger.info("evolution_message_ignored", extra={"reason": parsed.reason})
        return {"accepted": False, "reason": parsed.reason}

    if not state.store:
        raise RuntimeError("Redis store is not initialized")

    is_new = await state.store.mark_processed(parsed.message.message_id)
    if not is_new:
        if state.metrics:
            await state.metrics.record(event_instance, "duplicates")
        logger.info(
            "evolution_message_duplicate",
            extra={
                "message_id": parsed.message.message_id,
                "instance": parsed.message.instance,
                "phone": parsed.message.phone,
            },
        )
        return {"accepted": True, "duplicate": True}

    message = parsed.message
    if state.transcription_service:
        message = await state.transcription_service.enrich_message(message)

    try:
        await state.store.append_message(message)
    except Exception:
        await state.store.unmark_processed(message.message_id)
        logger.exception(
            "evolution_message_buffer_append_failed",
            extra={
                "message_id": message.message_id,
                "instance": message.instance,
                "phone": message.phone,
            },
        )
        raise

    if state.metrics:
        await state.metrics.record(message.instance, "buffered", count_hour=True)
        if message.message_type.value == "audio":
            await state.metrics.record(message.instance, "audio_messages")

    logger.info(
        "evolution_message_buffered",
        extra={
            "message_id": parsed.message.message_id,
            "instance": message.instance,
            "phone": message.phone,
            "message_type": message.message_type.value,
        },
    )

    return {
        "accepted": True,
        "duplicate": False,
        "session_id": message.session_id,
    }


@app.get("/admin/buffers", response_model=ActiveBuffersResponse, tags=["admin"])
async def admin_buffers(request: Request) -> ActiveBuffersResponse:
    """List sessions currently waiting in the buffer (useful before a demo)."""
    _verify_admin_token(request)
    if not state.store:
        raise RuntimeError("Redis store is not initialized")

    now = time.time()
    buffers: list[ActiveBufferInfo] = []
    for session_id in sorted(await state.store.get_active_sessions()):
        meta = await state.store.get_meta(session_id)
        if not meta:
            continue
        try:
            last_event_at = float(meta.get("last_event_at", "0"))
        except ValueError:
            last_event_at = 0.0
        count_raw = await state.store.redis.get(f"meta:{session_id}:count")
        buffers.append(
            ActiveBufferInfo(
                session_id=session_id,
                instance=meta.get("instance", ""),
                phone=meta.get("phone", ""),
                push_name=meta.get("push_name", ""),
                message_count=int(count_raw or 0),
                seconds_since_last_event=round(max(now - last_event_at, 0.0), 1),
            )
        )
    return ActiveBuffersResponse(total=len(buffers), buffers=buffers)


@app.get("/admin/dlq", response_model=DLQResponse, tags=["admin"])
async def admin_dlq(request: Request) -> DLQResponse:
    """List payloads waiting for redelivery to n8n."""
    _verify_admin_token(request)
    if not state.store:
        raise RuntimeError("Redis store is not initialized")

    entries = [
        DLQEntryInfo(
            dlq_id=entry.get("dlq_id", ""),
            instance=entry.get("payload", {}).get("instance", ""),
            phone=entry.get("payload", {}).get("phone", ""),
            attempts=int(entry.get("attempts", 0)),
            failed_at=entry.get("failed_at", ""),
            last_error=entry.get("last_error", ""),
            next_attempt_at=entry.get("next_attempt_at", ""),
        )
        for entry in await state.store.list_dlq_entries()
    ]
    return DLQResponse(total=len(entries), entries=entries)


@app.post("/admin/dlq/replay", tags=["admin"])
async def admin_dlq_replay(request: Request) -> dict[str, int]:
    """Schedule every parked payload for immediate redelivery."""
    _verify_admin_token(request)
    if not state.store:
        raise RuntimeError("Redis store is not initialized")

    rescheduled = await state.store.replay_dlq_now()
    logger.info("admin_dlq_replay", extra={"rescheduled": rescheduled})
    return {"rescheduled": rescheduled}


@app.delete("/admin/dlq/{dlq_id}", tags=["admin"])
async def admin_dlq_discard(dlq_id: str, request: Request) -> dict[str, bool]:
    """Discard one parked payload permanently."""
    _verify_admin_token(request)
    if not state.store:
        raise RuntimeError("Redis store is not initialized")

    removed = await state.store.remove_dlq_entry(dlq_id)
    logger.info("admin_dlq_discard", extra={"dlq_id": dlq_id, "removed": removed})
    return {"removed": removed}


@app.get("/admin/stats", tags=["admin"])
async def admin_stats(
    request: Request,
    instance: str,
    days: int = 7,
) -> dict[str, Any]:
    """Daily counters and hourly histogram for one WhatsApp instance."""
    _verify_admin_token(request)
    if not state.metrics:
        raise RuntimeError("Metrics recorder is not initialized")

    days = max(1, min(days, settings.stats_retention_days))
    daily = await state.metrics.read_daily(instance, days)
    hourly = await state.metrics.read_hourly_totals(instance, days)
    totals = {
        field: sum(int(row.get(field, 0)) for row in daily)
        for field in daily[0]
        if field != "date"
    }
    return {
        "instance": instance,
        "days": days,
        "totals": totals,
        "daily": daily,
        "hourly": {str(hour): count for hour, count in hourly.items()},
    }

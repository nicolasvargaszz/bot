"""FastAPI entry point for the WhatsApp message buffer service."""

from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
import logging
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from autobots.services.message_buffer.config import get_settings
from autobots.services.message_buffer.debouncer import DebounceWorker
from autobots.services.message_buffer.logging_config import configure_logging
from autobots.services.message_buffer.models import EvolutionWebhookParser
from autobots.services.message_buffer.n8n_client import N8NClient
from autobots.services.message_buffer.redis_store import RedisMessageStore
from autobots.services.message_buffer.transcription import AudioTranscriptionService


settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


class AppState:
    """Runtime dependencies attached to the FastAPI app."""

    store: RedisMessageStore | None = None
    worker: DebounceWorker | None = None
    worker_task: asyncio.Task[None] | None = None
    transcription_service: AudioTranscriptionService | None = None


state = AppState()


class HealthResponse(BaseModel):
    status: str
    redis: bool
    n8n_configured: bool


@asynccontextmanager
async def lifespan(_: FastAPI):
    state.store = RedisMessageStore.from_settings(settings)
    n8n_client = N8NClient(settings)
    state.transcription_service = AudioTranscriptionService(settings)
    state.worker = DebounceWorker(state.store, n8n_client, settings)
    state.worker_task = asyncio.create_task(state.worker.run_forever())
    try:
        yield
    finally:
        if state.worker:
            state.worker.stop()
        if state.worker_task:
            await state.worker_task
        if state.store:
            await state.store.close()


app = FastAPI(
    title="Autobots Message Buffer Service",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
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


@app.post("/webhook/evolution")
async def evolution_webhook(request: Request) -> dict[str, Any]:
    """Receive Evolution API webhook events and append them to Redis buffers."""
    try:
        payload = await request.json()
    except Exception as exc:
        logger.warning("evolution_webhook_invalid_json", extra={"error": str(exc)})
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    if not isinstance(payload, Mapping):
        raise HTTPException(status_code=400, detail="JSON payload must be an object")

    parsed = EvolutionWebhookParser.parse(payload)

    if not parsed.accepted or not parsed.message:
        logger.info("evolution_message_ignored", extra={"reason": parsed.reason})
        return {"accepted": False, "reason": parsed.reason}

    if not state.store:
        raise RuntimeError("Redis store is not initialized")

    is_new = await state.store.mark_processed(parsed.message.message_id)
    if not is_new:
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

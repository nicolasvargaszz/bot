"""Background worker that redelivers dead-lettered payloads to n8n.

Complements `DebounceWorker`: when a flush cannot reach n8n, the combined
payload is parked in the Redis DLQ instead of being lost. This worker retries
delivery with bounded exponential backoff until it succeeds or the attempt
budget (`DLQ_MAX_ATTEMPTS`) is exhausted.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from autobots.services.message_buffer.config import MessageBufferSettings
from autobots.services.message_buffer.metrics import MetricsRecorder
from autobots.services.message_buffer.models import CombinedMessagePayload
from autobots.services.message_buffer.n8n_client import N8NClient
from autobots.services.message_buffer.redis_store import RedisMessageStore
from autobots.services.message_buffer.retry import RetryPolicy, calculate_backoff_delay

logger = logging.getLogger(__name__)


class RedeliveryWorker:
    """Poll the DLQ and retry delivery of parked payloads."""

    def __init__(
        self,
        store: RedisMessageStore,
        n8n_client: N8NClient,
        settings: MessageBufferSettings,
        metrics: MetricsRecorder | None = None,
    ):
        self.store = store
        self.n8n_client = n8n_client
        self.settings = settings
        self.metrics = metrics
        self._stop_event = asyncio.Event()
        self._policy = RetryPolicy(
            max_attempts=settings.dlq_max_attempts,
            base_delay_seconds=settings.dlq_base_delay_seconds,
            max_delay_seconds=settings.dlq_max_delay_seconds,
        )

    async def run_forever(self) -> None:
        """Run the redelivery loop until stopped."""
        logger.info("redelivery_worker_started")
        while not self._stop_event.is_set():
            try:
                await self.process_due_entries()
            except Exception:
                logger.exception("redelivery_worker_iteration_failed")
            await asyncio.sleep(self.settings.dlq_poll_seconds)
        logger.info("redelivery_worker_stopped")

    def stop(self) -> None:
        self._stop_event.set()

    async def process_due_entries(self) -> int:
        """Attempt redelivery for every due DLQ entry. Returns deliveries made."""
        now = datetime.now(UTC).timestamp()
        delivered = 0
        for entry in await self.store.get_due_dlq_entries(now):
            if await self._redeliver(entry, now):
                delivered += 1
        return delivered

    async def _redeliver(self, entry: dict[str, Any], now: float) -> bool:
        dlq_id = entry.get("dlq_id", "")
        try:
            payload = CombinedMessagePayload.model_validate(entry["payload"])
        except (KeyError, ValueError):
            logger.error("dlq_entry_unparseable", extra={"dlq_id": dlq_id})
            await self.store.remove_dlq_entry(dlq_id)
            return False

        try:
            await self.n8n_client.send(payload)
        except Exception as exc:
            attempts = int(entry.get("attempts", 0)) + 1
            if attempts >= self.settings.dlq_max_attempts:
                await self.store.remove_dlq_entry(dlq_id)
                if self.metrics:
                    await self.metrics.record(payload.instance, "dlq_dropped")
                logger.error(
                    "dlq_entry_dropped",
                    extra={
                        "dlq_id": dlq_id,
                        "instance": payload.instance,
                        "phone": payload.phone,
                        "attempts": attempts,
                        "error": str(exc),
                    },
                )
                return False

            delay = calculate_backoff_delay(attempts, self._policy)
            await self.store.reschedule_dlq_entry(entry, str(exc), now + delay)
            logger.warning(
                "dlq_redelivery_failed",
                extra={
                    "dlq_id": dlq_id,
                    "attempts": attempts,
                    "next_attempt_in_seconds": delay,
                },
            )
            return False

        await self.store.remove_dlq_entry(dlq_id)
        if self.metrics:
            await self.metrics.record(payload.instance, "dlq_redelivered")
        logger.info(
            "dlq_redelivery_success",
            extra={
                "dlq_id": dlq_id,
                "instance": payload.instance,
                "phone": payload.phone,
                "buffer_id": payload.buffer_id,
            },
        )
        return True

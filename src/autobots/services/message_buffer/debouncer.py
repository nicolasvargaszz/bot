"""Debounce worker for flushing quiet Redis buffers to n8n."""

from __future__ import annotations

import asyncio
import logging
import time

from autobots.services.message_buffer.config import MessageBufferSettings
from autobots.services.message_buffer.models import combine_buffered_messages
from autobots.services.message_buffer.n8n_client import N8NClient
from autobots.services.message_buffer.redis_store import RedisMessageStore


logger = logging.getLogger(__name__)


class DebounceWorker:
    """Poll Redis for sessions whose debounce window has expired."""

    def __init__(
        self,
        store: RedisMessageStore,
        n8n_client: N8NClient,
        settings: MessageBufferSettings,
    ):
        self.store = store
        self.n8n_client = n8n_client
        self.settings = settings
        self._stop_event = asyncio.Event()

    async def run_forever(self) -> None:
        """Run the worker loop until stopped."""
        logger.info("debounce_worker_started")
        while not self._stop_event.is_set():
            try:
                await self.flush_ready_sessions()
            except Exception:
                logger.exception("debounce_worker_iteration_failed")
            await asyncio.sleep(self.settings.message_buffer_poll_seconds)
        logger.info("debounce_worker_stopped")

    def stop(self) -> None:
        self._stop_event.set()

    async def flush_ready_sessions(self) -> int:
        """Flush all sessions that are quiet for the configured debounce window."""
        flushed = 0
        now = time.time()
        for session_id in await self.store.get_active_sessions():
            meta = await self.store.get_meta(session_id)
            if not meta:
                await self.store.delete_session(session_id)
                continue

            try:
                last_event_at = float(meta.get("last_event_at", "0"))
            except ValueError:
                last_event_at = 0

            is_debounced = now - last_event_at >= self.settings.message_buffer_seconds
            is_too_old = now - last_event_at >= self.settings.message_buffer_max_age_seconds
            if not (is_debounced or is_too_old):
                continue

            if await self.flush_session(session_id):
                flushed += 1
        return flushed

    async def flush_session(self, session_id: str) -> bool:
        """Flush one session to n8n if the session lock can be acquired."""
        if not await self.store.acquire_lock(session_id):
            return False

        try:
            messages = await self.store.get_messages(session_id)
            if not messages:
                await self.store.delete_session(session_id)
                return False

            payload = combine_buffered_messages(messages)
            await self.n8n_client.send(payload)
            await self.store.delete_session(session_id)
            logger.info(
                "buffer_flushed",
                extra={
                    "session_id": session_id,
                    "buffer_id": payload.buffer_id,
                    "instance": payload.instance,
                    "phone": payload.phone,
                    "message_count": payload.message_count,
                },
            )
            return True
        except Exception as exc:
            try:
                messages = await self.store.get_messages(session_id)
                if messages:
                    payload = combine_buffered_messages(messages)
                    failed_key = await self.store.move_to_failed(payload, str(exc))
                    await self.store.delete_session(session_id)
                    logger.warning(
                        "buffer_moved_to_failed",
                        extra={
                            "session_id": session_id,
                            "failed_key": failed_key,
                            "error": str(exc),
                        },
                    )
            except Exception:
                logger.exception("failed_to_record_failed_buffer", extra={"session_id": session_id})
            return False
        finally:
            await self.store.release_lock(session_id)

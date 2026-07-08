"""Redis persistence for buffered WhatsApp messages."""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis

from autobots.services.message_buffer.config import MessageBufferSettings
from autobots.services.message_buffer.models import (
    BufferedMessage,
    CombinedMessagePayload,
    IncomingMessage,
    RedisKeyBuilder,
)

logger = logging.getLogger(__name__)


class RedisMessageStore:
    """Redis-backed storage for message buffers, dedupe keys, and failures."""

    def __init__(self, redis: Redis, settings: MessageBufferSettings):
        self.redis = redis
        self.settings = settings

    @classmethod
    def from_settings(cls, settings: MessageBufferSettings) -> RedisMessageStore:
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        return cls(redis=redis, settings=settings)

    async def close(self) -> None:
        await self.redis.aclose()

    async def ping(self) -> bool:
        return bool(await self.redis.ping())

    async def mark_processed(self, message_id: str) -> bool:
        """Return True when this message id has not been processed before."""
        key = RedisKeyBuilder.processed(message_id)
        return bool(
            await self.redis.set(
                key,
                "1",
                ex=self.settings.message_buffer_dedup_ttl_seconds,
                nx=True,
            )
        )

    async def unmark_processed(self, message_id: str) -> None:
        """Remove a dedupe key after a failed buffer append."""
        await self.redis.delete(RedisKeyBuilder.processed(message_id))

    async def append_message(self, message: IncomingMessage) -> None:
        """Append a normalized message to its Redis buffer and reset debounce."""
        session_id = message.session_id
        buffered = message.to_buffered_message()
        now = time.time()

        buffer_key = RedisKeyBuilder.buffer(session_id)
        meta_key = RedisKeyBuilder.meta(session_id)
        timer_key = RedisKeyBuilder.timer(session_id)

        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.rpush(buffer_key, buffered.model_dump_json())
            pipe.ltrim(buffer_key, -self.settings.message_buffer_max_messages, -1)
            pipe.hsetnx(meta_key, "first_event_at", str(now))
            pipe.hset(
                meta_key,
                mapping={
                    "instance": message.instance,
                    "phone": message.phone,
                    "push_name": message.push_name or "",
                    "last_event_at": str(now),
                    "last_event_id": message.message_id,
                },
            )
            pipe.incrby(f"{meta_key}:count", 1)
            pipe.expire(buffer_key, self.settings.message_buffer_max_age_seconds)
            pipe.expire(meta_key, self.settings.message_buffer_max_age_seconds)
            pipe.expire(f"{meta_key}:count", self.settings.message_buffer_max_age_seconds)
            pipe.set(
                timer_key,
                str(now),
                ex=max(self.settings.message_buffer_seconds, 1),
            )
            pipe.sadd(RedisKeyBuilder.active_sessions, session_id)
            await pipe.execute()

    async def get_active_sessions(self) -> set[str]:
        return set(await self.redis.smembers(RedisKeyBuilder.active_sessions))

    async def get_meta(self, session_id: str) -> dict[str, str]:
        return dict(await self.redis.hgetall(RedisKeyBuilder.meta(session_id)))

    async def get_messages(self, session_id: str) -> list[BufferedMessage]:
        raw_messages = await self.redis.lrange(RedisKeyBuilder.buffer(session_id), 0, -1)
        messages: list[BufferedMessage] = []
        for raw in raw_messages:
            try:
                messages.append(BufferedMessage.model_validate_json(raw))
            except ValueError:
                logger.warning("invalid_buffered_message_json", extra={"session_id": session_id})
        return messages

    async def delete_session(self, session_id: str) -> None:
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.delete(
                RedisKeyBuilder.buffer(session_id),
                RedisKeyBuilder.meta(session_id),
                RedisKeyBuilder.timer(session_id),
                f"{RedisKeyBuilder.meta(session_id)}:count",
            )
            pipe.srem(RedisKeyBuilder.active_sessions, session_id)
            await pipe.execute()

    async def acquire_lock(self, session_id: str, ttl_seconds: int = 30) -> bool:
        return bool(await self.redis.set(RedisKeyBuilder.lock(session_id), "1", ex=ttl_seconds, nx=True))

    async def release_lock(self, session_id: str) -> None:
        await self.redis.delete(RedisKeyBuilder.lock(session_id))

    # --- Dead-letter queue -------------------------------------------------
    #
    # When a combined payload cannot be delivered to n8n, it is parked here
    # instead of being lost. `dlq:pending` is a sorted set whose score is the
    # unix timestamp of the next delivery attempt; the payload itself lives in
    # a `dlq:entry:*` key with its own retention TTL.

    async def push_to_dlq(self, payload: CombinedMessagePayload, error: str) -> str:
        """Park an undeliverable payload for later redelivery. Returns the DLQ id."""
        now = datetime.now(UTC)
        dlq_id = f"{payload.buffer_id}:{int(now.timestamp())}"
        entry: dict[str, Any] = {
            "dlq_id": dlq_id,
            "payload": payload.model_dump(mode="json"),
            "first_error": error,
            "last_error": error,
            "attempts": 0,
            "failed_at": now.isoformat(),
        }
        next_attempt_at = now.timestamp() + self.settings.dlq_base_delay_seconds
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.set(
                RedisKeyBuilder.dlq_entry(dlq_id),
                json.dumps(entry, ensure_ascii=False, default=str),
                ex=self.settings.dlq_retention_seconds,
            )
            pipe.zadd(RedisKeyBuilder.dlq_pending, {dlq_id: next_attempt_at})
            await pipe.execute()
        return dlq_id

    async def get_due_dlq_entries(self, now: float, limit: int = 10) -> list[dict[str, Any]]:
        """Return DLQ entries whose next delivery attempt is due, pruning expired ones."""
        dlq_ids = await self.redis.zrangebyscore(
            RedisKeyBuilder.dlq_pending, "-inf", now, start=0, num=limit
        )
        entries: list[dict[str, Any]] = []
        for dlq_id in dlq_ids:
            raw = await self.redis.get(RedisKeyBuilder.dlq_entry(dlq_id))
            if raw is None:
                # Entry expired past retention; drop the dangling pointer.
                await self.redis.zrem(RedisKeyBuilder.dlq_pending, dlq_id)
                continue
            try:
                entries.append(json.loads(raw))
            except ValueError:
                logger.warning("invalid_dlq_entry_json", extra={"dlq_id": dlq_id})
                await self.remove_dlq_entry(dlq_id)
        return entries

    async def reschedule_dlq_entry(
        self,
        entry: dict[str, Any],
        error: str,
        next_attempt_at: float,
    ) -> None:
        """Record a failed redelivery attempt and schedule the next one."""
        dlq_id = entry["dlq_id"]
        entry["attempts"] = int(entry.get("attempts", 0)) + 1
        entry["last_error"] = error
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.set(
                RedisKeyBuilder.dlq_entry(dlq_id),
                json.dumps(entry, ensure_ascii=False, default=str),
                keepttl=True,
            )
            pipe.zadd(RedisKeyBuilder.dlq_pending, {dlq_id: next_attempt_at})
            await pipe.execute()

    async def remove_dlq_entry(self, dlq_id: str) -> bool:
        """Delete a DLQ entry after successful redelivery or explicit discard."""
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.delete(RedisKeyBuilder.dlq_entry(dlq_id))
            pipe.zrem(RedisKeyBuilder.dlq_pending, dlq_id)
            deleted, removed = await pipe.execute()
        return bool(deleted or removed)

    async def list_dlq_entries(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return pending DLQ entries with their scheduled next attempt."""
        scored = await self.redis.zrange(
            RedisKeyBuilder.dlq_pending, 0, limit - 1, withscores=True
        )
        entries: list[dict[str, Any]] = []
        for dlq_id, next_attempt_at in scored:
            raw = await self.redis.get(RedisKeyBuilder.dlq_entry(dlq_id))
            if raw is None:
                continue
            try:
                entry = json.loads(raw)
            except ValueError:
                continue
            entry["next_attempt_at"] = datetime.fromtimestamp(next_attempt_at, UTC).isoformat()
            entries.append(entry)
        return entries

    async def replay_dlq_now(self) -> int:
        """Schedule every pending DLQ entry for immediate redelivery."""
        dlq_ids = await self.redis.zrange(RedisKeyBuilder.dlq_pending, 0, -1)
        if not dlq_ids:
            return 0
        now = datetime.now(UTC).timestamp()
        await self.redis.zadd(
            RedisKeyBuilder.dlq_pending, {dlq_id: now for dlq_id in dlq_ids}
        )
        return len(dlq_ids)

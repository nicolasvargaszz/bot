"""Redis persistence for buffered WhatsApp messages."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import logging
import time
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
    def from_settings(cls, settings: MessageBufferSettings) -> "RedisMessageStore":
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

    async def move_to_failed(
        self,
        payload: CombinedMessagePayload,
        error: str,
    ) -> str:
        timestamp = int(datetime.now(UTC).timestamp())
        failed_key = RedisKeyBuilder.failed(payload.instance, payload.phone, timestamp)
        failed_payload: dict[str, Any] = {
            "error": error,
            "failed_at": datetime.now(UTC).isoformat(),
            "payload": payload.model_dump(mode="json"),
        }
        await self.redis.set(
            failed_key,
            json.dumps(failed_payload, ensure_ascii=False, default=str),
            ex=self.settings.message_buffer_max_age_seconds,
        )
        await self.redis.hset(
            f"{failed_key}:meta",
            mapping={
                "error": error,
                "failed_at": failed_payload["failed_at"],
                "buffer_id": payload.buffer_id,
            },
        )
        await self.redis.expire(f"{failed_key}:meta", self.settings.message_buffer_max_age_seconds)
        return failed_key

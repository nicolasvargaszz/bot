"""Per-instance operational metrics stored in Redis.

Counters power the admin `/admin/stats` endpoint and the Spanish pilot
report (`python -m autobots.reporting.pilot_report`). Recording must never
break the message pipeline: every write is wrapped and failures are logged
and swallowed.

Keys (see `RedisKeyBuilder`):
- ``stats:daily:{instance}:{YYYY-MM-DD}`` — hash of daily counters.
- ``stats:hourly:{instance}:{YYYY-MM-DD}`` — hash hour ("0".."23") → inbound
  messages, bucketed in the business timezone so "out of hours" means what
  the client thinks it means.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from redis.asyncio import Redis

from autobots.services.message_buffer.config import MessageBufferSettings
from autobots.services.message_buffer.models import RedisKeyBuilder

logger = logging.getLogger(__name__)

DAILY_FIELDS = (
    "received",
    "ignored",
    "duplicates",
    "buffered",
    "audio_messages",
    "flushes",
    "fragments_flushed",
    "forward_ok",
    "forward_failed",
    "dlq_redelivered",
    "dlq_dropped",
)


class MetricsRecorder:
    """Fire-and-forget Redis counters, bucketed per instance and local day."""

    def __init__(self, redis: Redis, settings: MessageBufferSettings):
        self.redis = redis
        self.settings = settings
        try:
            self._tz = ZoneInfo(settings.stats_timezone)
        except Exception:
            logger.warning(
                "invalid_stats_timezone", extra={"stats_timezone": settings.stats_timezone}
            )
            self._tz = UTC

    def _local_now(self) -> datetime:
        return datetime.now(UTC).astimezone(self._tz)

    async def record(self, instance: str, field: str, *, count_hour: bool = False) -> None:
        """Increment one daily counter (and optionally the hourly histogram)."""
        now = self._local_now()
        day = now.strftime("%Y-%m-%d")
        ttl = self.settings.stats_retention_days * 86400
        daily_key = RedisKeyBuilder.stats_daily(instance, day)
        try:
            async with self.redis.pipeline(transaction=False) as pipe:
                pipe.hincrby(daily_key, field, 1)
                pipe.expire(daily_key, ttl)
                if count_hour:
                    hourly_key = RedisKeyBuilder.stats_hourly(instance, day)
                    pipe.hincrby(hourly_key, str(now.hour), 1)
                    pipe.expire(hourly_key, ttl)
                await pipe.execute()
        except Exception:
            logger.warning(
                "metrics_record_failed",
                extra={"instance": instance, "field": field},
            )

    async def record_flush(self, instance: str, fragment_count: int) -> None:
        """Record one flushed buffer and how many fragments it combined."""
        now = self._local_now()
        day = now.strftime("%Y-%m-%d")
        ttl = self.settings.stats_retention_days * 86400
        daily_key = RedisKeyBuilder.stats_daily(instance, day)
        try:
            async with self.redis.pipeline(transaction=False) as pipe:
                pipe.hincrby(daily_key, "flushes", 1)
                pipe.hincrby(daily_key, "fragments_flushed", fragment_count)
                pipe.expire(daily_key, ttl)
                await pipe.execute()
        except Exception:
            logger.warning("metrics_record_failed", extra={"instance": instance, "field": "flushes"})

    async def read_daily(self, instance: str, days: int) -> list[dict[str, int | str]]:
        """Return one row per local day (oldest first), zero-filled fields."""
        rows: list[dict[str, int | str]] = []
        today = self._local_now().date()
        for offset in range(days - 1, -1, -1):
            day = today.fromordinal(today.toordinal() - offset).isoformat()
            raw = await self.redis.hgetall(RedisKeyBuilder.stats_daily(instance, day))
            row: dict[str, int | str] = {"date": day}
            for field in DAILY_FIELDS:
                try:
                    row[field] = int(raw.get(field, 0))
                except (TypeError, ValueError):
                    row[field] = 0
            rows.append(row)
        return rows

    async def read_hourly_totals(self, instance: str, days: int) -> dict[int, int]:
        """Return inbound-message counts summed per local hour over the window."""
        totals: dict[int, int] = {hour: 0 for hour in range(24)}
        today = self._local_now().date()
        for offset in range(days):
            day = today.fromordinal(today.toordinal() - offset).isoformat()
            raw = await self.redis.hgetall(RedisKeyBuilder.stats_hourly(instance, day))
            for hour_str, count in raw.items():
                try:
                    totals[int(hour_str)] += int(count)
                except (KeyError, TypeError, ValueError):
                    continue
        return totals

"""Dead-letter queue: parking, redelivery, backoff, and replay."""

from datetime import UTC, datetime

import pytest
from fakeredis import FakeAsyncRedis

from autobots.services.message_buffer.config import MessageBufferSettings
from autobots.services.message_buffer.debouncer import DebounceWorker
from autobots.services.message_buffer.metrics import MetricsRecorder
from autobots.services.message_buffer.models import (
    CombinedMessagePayload,
    IncomingMessage,
    MessageType,
    RedisKeyBuilder,
)
from autobots.services.message_buffer.n8n_client import N8NDeliveryError
from autobots.services.message_buffer.redelivery import RedeliveryWorker
from autobots.services.message_buffer.redis_store import RedisMessageStore


def _settings(**overrides) -> MessageBufferSettings:
    defaults = {
        "dlq_base_delay_seconds": 30.0,
        "dlq_max_delay_seconds": 900.0,
        "dlq_max_attempts": 3,
        "dlq_retention_seconds": 3600,
    }
    defaults.update(overrides)
    return MessageBufferSettings(**defaults)


def _payload(buffer_id: str = "buf-1") -> CombinedMessagePayload:
    now = datetime.now(UTC)
    return CombinedMessagePayload(
        buffer_id=buffer_id,
        instance="demo",
        phone="595981123456",
        combined_text="Hola, precio?",
        message_count=2,
        event_ids=["m1", "m2"],
        contains_audio=False,
        first_timestamp=now,
        last_timestamp=now,
    )


class FlakyN8NClient:
    """Fails the first `failures` sends, then succeeds."""

    def __init__(self, failures: int = 0):
        self.failures = failures
        self.sent: list[CombinedMessagePayload] = []

    async def send(self, payload: CombinedMessagePayload) -> None:
        if self.failures > 0:
            self.failures -= 1
            raise N8NDeliveryError("n8n returned HTTP 502")
        self.sent.append(payload)


@pytest.fixture
def store() -> RedisMessageStore:
    return RedisMessageStore(FakeAsyncRedis(decode_responses=True), _settings())


@pytest.mark.asyncio
async def test_push_to_dlq_schedules_first_retry_after_base_delay(store):
    before = datetime.now(UTC).timestamp()

    dlq_id = await store.push_to_dlq(_payload(), "boom")

    score = await store.redis.zscore(RedisKeyBuilder.dlq_pending, dlq_id)
    assert score >= before + store.settings.dlq_base_delay_seconds
    entries = await store.list_dlq_entries()
    assert len(entries) == 1
    assert entries[0]["first_error"] == "boom"
    assert entries[0]["attempts"] == 0


@pytest.mark.asyncio
async def test_get_due_dlq_entries_respects_schedule(store):
    dlq_id = await store.push_to_dlq(_payload(), "boom")
    now = datetime.now(UTC).timestamp()

    assert await store.get_due_dlq_entries(now) == []

    due = await store.get_due_dlq_entries(now + store.settings.dlq_base_delay_seconds + 1)
    assert [entry["dlq_id"] for entry in due] == [dlq_id]


@pytest.mark.asyncio
async def test_get_due_dlq_entries_prunes_expired_payloads(store):
    dlq_id = await store.push_to_dlq(_payload(), "boom")
    await store.redis.delete(RedisKeyBuilder.dlq_entry(dlq_id))

    due = await store.get_due_dlq_entries(datetime.now(UTC).timestamp() + 10_000)

    assert due == []
    assert await store.redis.zcard(RedisKeyBuilder.dlq_pending) == 0


@pytest.mark.asyncio
async def test_replay_dlq_now_makes_all_entries_due(store):
    await store.push_to_dlq(_payload("buf-1"), "boom")
    await store.push_to_dlq(_payload("buf-2"), "boom")

    rescheduled = await store.replay_dlq_now()

    assert rescheduled == 2
    due = await store.get_due_dlq_entries(datetime.now(UTC).timestamp() + 1)
    assert len(due) == 2


@pytest.mark.asyncio
async def test_redelivery_success_removes_entry_and_counts_metric(store):
    client = FlakyN8NClient(failures=0)
    metrics = MetricsRecorder(store.redis, store.settings)
    worker = RedeliveryWorker(store, client, store.settings, metrics=metrics)
    await store.push_to_dlq(_payload(), "boom")
    await store.replay_dlq_now()

    delivered = await worker.process_due_entries()

    assert delivered == 1
    assert [sent.buffer_id for sent in client.sent] == ["buf-1"]
    assert await store.list_dlq_entries() == []
    daily = await metrics.read_daily("demo", 1)
    assert daily[-1]["dlq_redelivered"] == 1


@pytest.mark.asyncio
async def test_redelivery_failure_reschedules_with_backoff(store):
    client = FlakyN8NClient(failures=10)
    worker = RedeliveryWorker(store, client, store.settings)
    await store.push_to_dlq(_payload(), "boom")
    await store.replay_dlq_now()

    delivered = await worker.process_due_entries()

    assert delivered == 0
    entries = await store.list_dlq_entries()
    assert len(entries) == 1
    assert entries[0]["attempts"] == 1
    assert entries[0]["last_error"] == "n8n returned HTTP 502"
    # Not due again until the backoff delay passes.
    assert await store.get_due_dlq_entries(datetime.now(UTC).timestamp() + 1) == []


@pytest.mark.asyncio
async def test_redelivery_drops_entry_after_max_attempts(store):
    client = FlakyN8NClient(failures=10)
    metrics = MetricsRecorder(store.redis, store.settings)
    worker = RedeliveryWorker(store, client, store.settings, metrics=metrics)
    await store.push_to_dlq(_payload(), "boom")

    for _ in range(store.settings.dlq_max_attempts):
        await store.replay_dlq_now()
        await worker.process_due_entries()

    assert await store.list_dlq_entries() == []
    daily = await metrics.read_daily("demo", 1)
    assert daily[-1]["dlq_dropped"] == 1


@pytest.mark.asyncio
async def test_flush_failure_parks_payload_in_dlq(store):
    client = FlakyN8NClient(failures=10)
    worker = DebounceWorker(store, client, store.settings)
    message = IncomingMessage(
        instance="demo",
        phone="595981123456",
        message_id="m1",
        message_type=MessageType.TEXT,
        text="Hola",
    )
    await store.append_message(message)

    flushed = await worker.flush_session(message.session_id)

    assert flushed is False
    entries = await store.list_dlq_entries()
    assert len(entries) == 1
    assert entries[0]["payload"]["phone"] == "595981123456"
    # The session buffer is cleared; the payload lives only in the DLQ now.
    assert await store.get_active_sessions() == set()

"""Metrics recorder: daily counters, hourly histogram, and failure isolation."""

import pytest
from fakeredis import FakeAsyncRedis

from autobots.services.message_buffer.config import MessageBufferSettings
from autobots.services.message_buffer.metrics import MetricsRecorder


def _recorder(redis=None, **overrides) -> MetricsRecorder:
    settings = MessageBufferSettings(**overrides)
    return MetricsRecorder(redis or FakeAsyncRedis(decode_responses=True), settings)


@pytest.mark.asyncio
async def test_record_increments_daily_counter():
    recorder = _recorder()

    await recorder.record("demo", "buffered")
    await recorder.record("demo", "buffered")
    await recorder.record("demo", "duplicates")

    daily = await recorder.read_daily("demo", 1)
    assert daily[-1]["buffered"] == 2
    assert daily[-1]["duplicates"] == 1
    assert daily[-1]["forward_ok"] == 0  # zero-filled fields


@pytest.mark.asyncio
async def test_record_with_hour_feeds_hourly_histogram():
    recorder = _recorder()

    await recorder.record("demo", "buffered", count_hour=True)

    hourly = await recorder.read_hourly_totals("demo", 1)
    assert sum(hourly.values()) == 1
    local_hour = recorder._local_now().hour
    assert hourly[local_hour] == 1


@pytest.mark.asyncio
async def test_record_flush_tracks_fragments():
    recorder = _recorder()

    await recorder.record_flush("demo", 3)
    await recorder.record_flush("demo", 5)

    daily = await recorder.read_daily("demo", 1)
    assert daily[-1]["flushes"] == 2
    assert daily[-1]["fragments_flushed"] == 8


@pytest.mark.asyncio
async def test_read_daily_returns_one_row_per_day_oldest_first():
    recorder = _recorder()

    rows = await recorder.read_daily("demo", 3)

    assert len(rows) == 3
    assert rows[0]["date"] < rows[1]["date"] < rows[2]["date"]


@pytest.mark.asyncio
async def test_instances_are_isolated():
    redis = FakeAsyncRedis(decode_responses=True)
    recorder = _recorder(redis)

    await recorder.record("cliente-a", "buffered")

    assert (await recorder.read_daily("cliente-a", 1))[-1]["buffered"] == 1
    assert (await recorder.read_daily("cliente-b", 1))[-1]["buffered"] == 0


@pytest.mark.asyncio
async def test_recording_failure_never_raises():
    class BrokenRedis:
        def pipeline(self, transaction=False):
            raise ConnectionError("redis is down")

    settings = MessageBufferSettings()
    recorder = MetricsRecorder(BrokenRedis(), settings)

    await recorder.record("demo", "buffered")  # must not raise
    await recorder.record_flush("demo", 2)  # must not raise


def test_invalid_timezone_falls_back_to_utc():
    recorder = _recorder(stats_timezone="Not/AZone")

    assert recorder._local_now().tzinfo is not None

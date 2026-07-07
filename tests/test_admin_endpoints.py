"""Admin API: fail-closed token auth and endpoint behavior."""

import pytest
from fakeredis import FakeAsyncRedis
from fastapi import HTTPException
from starlette.requests import Request

from autobots.services.message_buffer import app as buffer_app
from autobots.services.message_buffer.config import MessageBufferSettings
from autobots.services.message_buffer.metrics import MetricsRecorder
from autobots.services.message_buffer.models import IncomingMessage, MessageType
from autobots.services.message_buffer.redis_store import RedisMessageStore


def _request_with_token(token: str = "") -> Request:
    headers = []
    if token:
        headers.append((b"x-autobots-admin-token", token.encode("utf-8")))
    return Request({"type": "http", "headers": headers, "client": ("127.0.0.1", 12345)})


def test_admin_fails_closed_when_token_not_configured(monkeypatch):
    monkeypatch.setattr(buffer_app.settings, "admin_api_token", "")

    with pytest.raises(HTTPException) as exc:
        buffer_app._verify_admin_token(_request_with_token("anything"))

    assert exc.value.status_code == 503


def test_admin_rejects_wrong_token(monkeypatch):
    monkeypatch.setattr(buffer_app.settings, "admin_api_token", "right-token")

    with pytest.raises(HTTPException) as exc:
        buffer_app._verify_admin_token(_request_with_token("wrong-token"))

    assert exc.value.status_code == 401


def test_admin_rejects_missing_token(monkeypatch):
    monkeypatch.setattr(buffer_app.settings, "admin_api_token", "right-token")

    with pytest.raises(HTTPException) as exc:
        buffer_app._verify_admin_token(_request_with_token())

    assert exc.value.status_code == 401


def test_admin_accepts_matching_token(monkeypatch):
    monkeypatch.setattr(buffer_app.settings, "admin_api_token", "right-token")

    buffer_app._verify_admin_token(_request_with_token("right-token"))


@pytest.fixture
def wired_state(monkeypatch):
    """Wire the app state to fakeredis and authorize admin requests."""
    settings = MessageBufferSettings()
    store = RedisMessageStore(FakeAsyncRedis(decode_responses=True), settings)
    monkeypatch.setattr(buffer_app.settings, "admin_api_token", "token")
    monkeypatch.setattr(buffer_app.state, "store", store)
    monkeypatch.setattr(buffer_app.state, "metrics", MetricsRecorder(store.redis, settings))
    return store


@pytest.mark.asyncio
async def test_admin_buffers_lists_waiting_sessions(wired_state):
    store = wired_state
    await store.append_message(
        IncomingMessage(
            instance="demo",
            phone="595981123456",
            message_id="m1",
            message_type=MessageType.TEXT,
            text="Hola",
        )
    )

    response = await buffer_app.admin_buffers(_request_with_token("token"))

    assert response.total == 1
    assert response.buffers[0].instance == "demo"
    assert response.buffers[0].phone == "595981123456"
    assert response.buffers[0].message_count == 1


@pytest.mark.asyncio
async def test_admin_stats_aggregates_days(wired_state):
    await buffer_app.state.metrics.record("demo", "buffered", count_hour=True)
    await buffer_app.state.metrics.record("demo", "buffered", count_hour=True)

    stats = await buffer_app.admin_stats(_request_with_token("token"), instance="demo", days=2)

    assert stats["totals"]["buffered"] == 2
    assert len(stats["daily"]) == 2
    assert sum(int(count) for count in stats["hourly"].values()) == 2

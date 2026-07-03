import base64
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from autobots.dashboard.app import app as dashboard_app
from autobots.services.message_buffer import app as buffer_app
from autobots.services.message_buffer.config import MessageBufferSettings
from autobots.services.message_buffer.models import CombinedMessagePayload
from autobots.services.message_buffer.n8n_client import N8NClient, N8NDeliveryError


def _basic_auth(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def test_dashboard_requires_auth_password(monkeypatch):
    monkeypatch.setenv("DASHBOARD_AUTH_ENABLED", "true")
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)

    response = dashboard_app.test_client().get("/")

    assert response.status_code == 503


def test_dashboard_rejects_missing_auth(monkeypatch):
    monkeypatch.setenv("DASHBOARD_AUTH_ENABLED", "true")
    monkeypatch.setenv("DASHBOARD_USERNAME", "nicolas")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "local-secret")

    response = dashboard_app.test_client().get("/")

    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers


def test_dashboard_accepts_basic_auth(monkeypatch):
    monkeypatch.setenv("DASHBOARD_AUTH_ENABLED", "true")
    monkeypatch.setenv("DASHBOARD_USERNAME", "nicolas")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "local-secret")

    response = dashboard_app.test_client().get(
        "/",
        headers={"Authorization": _basic_auth("nicolas", "local-secret")},
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store, private"
    assert response.headers["X-Frame-Options"] == "DENY"


def _payload() -> CombinedMessagePayload:
    timestamp = datetime.now(UTC)
    return CombinedMessagePayload(
        buffer_id="buffer-1",
        instance="autobots-demo",
        phone="595981123456",
        combined_text="Hola",
        message_count=1,
        event_ids=["msg-1"],
        contains_audio=False,
        first_timestamp=timestamp,
        last_timestamp=timestamp,
    )


def _request_with_secret(secret: str = "") -> Request:
    headers = []
    if secret:
        headers.append((b"x-autobots-webhook-secret", secret.encode("utf-8")))
    return Request({"type": "http", "headers": headers, "client": ("127.0.0.1", 12345)})


def test_buffer_webhook_accepts_matching_shared_secret(monkeypatch):
    monkeypatch.setattr(buffer_app.settings, "evolution_buffer_webhook_secret", "evolution-secret")

    buffer_app._verify_evolution_webhook_secret(_request_with_secret("evolution-secret"))


def test_buffer_webhook_rejects_missing_shared_secret(monkeypatch):
    monkeypatch.setattr(buffer_app.settings, "evolution_buffer_webhook_secret", "evolution-secret")

    with pytest.raises(HTTPException) as exc:
        buffer_app._verify_evolution_webhook_secret(_request_with_secret())

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_n8n_client_requires_shared_secret():
    client = N8NClient(
        MessageBufferSettings(
            n8n_webhook_url="http://n8n:5678/webhook/whatsapp-buffer",
        ),
    )

    with pytest.raises(N8NDeliveryError):
        await client.send(_payload())


@pytest.mark.asyncio
async def test_n8n_client_sends_shared_secret_header(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(
        "autobots.services.message_buffer.n8n_client.httpx.AsyncClient",
        FakeAsyncClient,
    )

    client = N8NClient(
        MessageBufferSettings(
            n8n_webhook_url="http://n8n:5678/webhook/whatsapp-buffer",
            n8n_buffered_webhook_secret="buffer-to-n8n-secret",
        ),
    )

    await client.send(_payload())

    assert captured["url"] == "http://n8n:5678/webhook/whatsapp-buffer"
    assert captured["headers"] == {
        "X-Autobots-Webhook-Secret": "buffer-to-n8n-secret",
    }

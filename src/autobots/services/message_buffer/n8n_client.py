"""Async n8n webhook client."""

from __future__ import annotations

import logging

import httpx

from autobots.services.message_buffer.config import MessageBufferSettings
from autobots.services.message_buffer.errors import N8NUnavailableError
from autobots.services.message_buffer.models import CombinedMessagePayload


logger = logging.getLogger(__name__)


class N8NDeliveryError(N8NUnavailableError):
    """Raised when a buffered payload cannot be delivered to n8n."""


class N8NClient:
    """Minimal async client for the buffered n8n webhook."""

    def __init__(self, settings: MessageBufferSettings):
        self.settings = settings

    async def send(self, payload: CombinedMessagePayload) -> None:
        """POST a combined message payload to n8n."""
        if not self.settings.n8n_webhook_url:
            raise N8NDeliveryError("N8N_WEBHOOK_URL is not configured")

        async with httpx.AsyncClient(timeout=self.settings.n8n_request_timeout_seconds) as client:
            response = await client.post(
                self.settings.n8n_webhook_url,
                json=payload.model_dump(mode="json"),
            )

        if response.status_code >= 400:
            logger.warning(
                "n8n_delivery_failed",
                extra={
                    "status_code": response.status_code,
                    "buffer_id": payload.buffer_id,
                    "instance": payload.instance,
                    "phone": payload.phone,
                },
            )
            raise N8NDeliveryError(f"n8n returned HTTP {response.status_code}")

        logger.info(
            "n8n_delivery_success",
            extra={
                "buffer_id": payload.buffer_id,
                "instance": payload.instance,
                "phone": payload.phone,
                "message_count": payload.message_count,
            },
        )

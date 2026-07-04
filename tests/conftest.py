"""Shared test fixtures."""

import pytest

from autobots.services.message_buffer.config import MessageBufferSettings


@pytest.fixture(autouse=True)
def _ignore_local_dotenv(monkeypatch):
    """Keep tests deterministic on machines that have a filled-in .env.

    MessageBufferSettings reads ``.env`` from the working directory by
    default; tests must see only the values they set explicitly.
    """
    monkeypatch.setitem(MessageBufferSettings.model_config, "env_file", None)
    for var in ("N8N_BUFFERED_WEBHOOK_SECRET", "EVOLUTION_BUFFER_WEBHOOK_SECRET"):
        monkeypatch.delenv(var, raising=False)

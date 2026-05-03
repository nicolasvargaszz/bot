"""Configuration for the message buffer service."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MessageBufferSettings(BaseSettings):
    """Settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    redis_url: str = "redis://localhost:6379/0"
    n8n_webhook_url: str = ""
    message_buffer_seconds: int = Field(default=8, ge=1)
    message_buffer_max_messages: int = Field(default=20, ge=1)
    message_buffer_max_age_seconds: int = Field(default=120, ge=30)
    message_buffer_dedup_ttl_seconds: int = Field(default=86400, ge=60)
    message_buffer_poll_seconds: float = Field(default=1.0, ge=0.1)
    n8n_request_timeout_seconds: float = Field(default=10.0, ge=1)
    transcription_provider: Literal["disabled", "whisper_api", "local_whisper"] = "disabled"
    whisper_api_key: str = ""
    whisper_api_url: str = "https://api.openai.com/v1/audio/transcriptions"
    audio_download_timeout_seconds: float = Field(default=15.0, ge=1)
    max_audio_size_mb: float = Field(default=10.0, ge=0.1)
    log_level: str = "INFO"

    @property
    def max_audio_size_bytes(self) -> int:
        """Return the configured maximum audio size in bytes."""
        return int(self.max_audio_size_mb * 1024 * 1024)


@lru_cache
def get_settings() -> MessageBufferSettings:
    """Return cached service settings."""
    return MessageBufferSettings()

"""Provider-based voice transcription for buffered WhatsApp audio."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
import logging
from typing import Any

import httpx

from autobots.services.message_buffer.audio import (
    AUDIO_TRANSCRIPTION_FAILURE_PLACEHOLDER,
    delete_temp_file,
    format_audio_transcription,
    save_audio_to_temp_file,
)
from autobots.services.message_buffer.config import MessageBufferSettings
from autobots.services.message_buffer.models import IncomingMessage, MessageType


logger = logging.getLogger(__name__)


class TranscriptionError(RuntimeError):
    """Raised when a provider cannot transcribe an audio message."""


class TranscriptionProvider(ABC):
    """Interface for voice-to-text providers."""

    @abstractmethod
    async def transcribe(self, audio_path: Path, audio_metadata: dict[str, Any]) -> str:
        """Return transcribed text for a local audio file."""


class DisabledTranscriptionProvider(TranscriptionProvider):
    """Provider that intentionally does not transcribe audio."""

    async def transcribe(self, audio_path: Path, audio_metadata: dict[str, Any]) -> str:
        raise TranscriptionError("transcription provider is disabled")


class LocalWhisperProvider(TranscriptionProvider):
    """Placeholder for a future local Whisper implementation."""

    async def transcribe(self, audio_path: Path, audio_metadata: dict[str, Any]) -> str:
        raise TranscriptionError("local_whisper provider is not implemented")


class WhisperApiProvider(TranscriptionProvider):
    """OpenAI Whisper-compatible HTTP transcription provider."""

    def __init__(self, settings: MessageBufferSettings):
        self.settings = settings

    async def transcribe(self, audio_path: Path, audio_metadata: dict[str, Any]) -> str:
        if not self.settings.whisper_api_key:
            raise TranscriptionError("WHISPER_API_KEY is not configured")
        if not self.settings.whisper_api_url:
            raise TranscriptionError("WHISPER_API_URL is not configured")

        headers = {
            "Authorization": f"Bearer {self.settings.whisper_api_key}",
        }
        data = {
            "model": "whisper-1",
        }
        mime_type = audio_metadata.get("mime_type") or "application/octet-stream"

        try:
            with audio_path.open("rb") as audio_file:
                files = {
                    "file": (audio_path.name, audio_file, mime_type),
                }
                async with httpx.AsyncClient(timeout=self.settings.audio_download_timeout_seconds) as client:
                    response = await client.post(
                        self.settings.whisper_api_url,
                        headers=headers,
                        data=data,
                        files=files,
                    )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TranscriptionError("whisper API request failed") from exc

        payload = response.json()
        text = payload.get("text") or payload.get("transcription") or payload.get("output_text")
        if not text:
            raise TranscriptionError("whisper API response did not include text")
        return str(text)


def build_transcription_provider(settings: MessageBufferSettings) -> TranscriptionProvider:
    """Build the configured transcription provider."""
    if settings.transcription_provider == "disabled":
        return DisabledTranscriptionProvider()
    if settings.transcription_provider == "whisper_api":
        return WhisperApiProvider(settings)
    if settings.transcription_provider == "local_whisper":
        return LocalWhisperProvider()
    return DisabledTranscriptionProvider()


class AudioTranscriptionService:
    """Download and transcribe incoming audio messages before Redis buffering."""

    def __init__(
        self,
        settings: MessageBufferSettings,
        provider: TranscriptionProvider | None = None,
    ):
        self.settings = settings
        self.provider = provider or build_transcription_provider(settings)

    async def enrich_message(self, message: IncomingMessage) -> IncomingMessage:
        """Return a copy of the message with transcription text if audio is present."""
        if message.message_type != MessageType.AUDIO or not message.audio:
            return message

        if isinstance(self.provider, DisabledTranscriptionProvider):
            return self._message_with_transcription(
                message,
                AUDIO_TRANSCRIPTION_FAILURE_PLACEHOLDER,
                "disabled",
            )

        if isinstance(self.provider, LocalWhisperProvider):
            logger.warning(
                "audio_transcription_provider_not_implemented",
                extra={
                    "provider": self.settings.transcription_provider,
                    "message_id": message.message_id,
                    "instance": message.instance,
                    "phone": message.phone,
                },
            )
            return self._message_with_transcription(
                message,
                AUDIO_TRANSCRIPTION_FAILURE_PLACEHOLDER,
                "failed",
            )

        transcription_text = AUDIO_TRANSCRIPTION_FAILURE_PLACEHOLDER
        transcription_status = "failed"
        temp_path: Path | None = None

        try:
            temp_path = await save_audio_to_temp_file(message.audio, self.settings)
            raw_text = await self.provider.transcribe(temp_path, message.audio)
            transcription_text = format_audio_transcription(raw_text)
            transcription_status = "success"
        except Exception as exc:
            logger.warning(
                "audio_transcription_failed",
                extra={
                    "provider": self.settings.transcription_provider,
                    "message_id": message.message_id,
                    "instance": message.instance,
                    "phone": message.phone,
                    "error_type": exc.__class__.__name__,
                },
            )
        finally:
            delete_temp_file(temp_path)

        return self._message_with_transcription(message, transcription_text, transcription_status)

    def _message_with_transcription(
        self,
        message: IncomingMessage,
        text: str,
        status: str,
    ) -> IncomingMessage:
        audio = dict(message.audio or {})
        audio["transcription_provider"] = self.settings.transcription_provider
        audio["transcription_status"] = status

        return message.model_copy(
            update={
                "text": text,
                "audio": audio,
            }
        )

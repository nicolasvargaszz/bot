from datetime import UTC, datetime
from pathlib import Path

import pytest

from autobots.services.message_buffer.audio import (
    AUDIO_TRANSCRIPTION_FAILURE_PLACEHOLDER,
    AudioTooLargeError,
    format_audio_transcription,
    validate_audio_size,
)
from autobots.services.message_buffer.config import MessageBufferSettings
from autobots.services.message_buffer.models import IncomingMessage, MessageType
from autobots.services.message_buffer.transcription import (
    AudioTranscriptionService,
    DisabledTranscriptionProvider,
    LocalWhisperProvider,
    TranscriptionError,
    TranscriptionProvider,
    WhisperApiProvider,
    build_transcription_provider,
)


class FakeSuccessProvider(TranscriptionProvider):
    async def transcribe(self, audio_path: Path, audio_metadata: dict) -> str:
        assert audio_path.exists()
        return "Hola, estoy interesado en el departamento."


class FakeFailureProvider(TranscriptionProvider):
    async def transcribe(self, audio_path: Path, audio_metadata: dict) -> str:
        raise TranscriptionError("boom")


def make_audio_message() -> IncomingMessage:
    return IncomingMessage(
        instance="autobots-demo",
        phone="595981123456",
        message_id="audio-1",
        timestamp=datetime(2026, 5, 2, tzinfo=UTC),
        message_type=MessageType.AUDIO,
        audio={
            "base64": "aGVsbG8=",
            "mime_type": "audio/ogg",
            "file_length": 5,
        },
    )


def test_provider_selection():
    assert isinstance(
        build_transcription_provider(MessageBufferSettings(transcription_provider="disabled")),
        DisabledTranscriptionProvider,
    )
    assert isinstance(
        build_transcription_provider(MessageBufferSettings(transcription_provider="whisper_api")),
        WhisperApiProvider,
    )
    assert isinstance(
        build_transcription_provider(MessageBufferSettings(transcription_provider="local_whisper")),
        LocalWhisperProvider,
    )


@pytest.mark.asyncio
async def test_disabled_transcription_returns_failure_placeholder_without_download():
    settings = MessageBufferSettings(transcription_provider="disabled")
    message = make_audio_message().model_copy(update={"audio": {"url": "https://example.test/audio.ogg"}})
    service = AudioTranscriptionService(settings)

    enriched = await service.enrich_message(message)

    assert enriched.text == AUDIO_TRANSCRIPTION_FAILURE_PLACEHOLDER
    assert enriched.audio["transcription_provider"] == "disabled"
    assert enriched.audio["transcription_status"] == "disabled"


def test_audio_size_validation_rejects_large_audio():
    with pytest.raises(AudioTooLargeError):
        validate_audio_size(size_bytes=11 * 1024 * 1024, max_size_bytes=10 * 1024 * 1024)


@pytest.mark.asyncio
async def test_successful_transcription_is_prefixed_for_buffering():
    settings = MessageBufferSettings(transcription_provider="whisper_api")
    service = AudioTranscriptionService(settings, provider=FakeSuccessProvider())

    enriched = await service.enrich_message(make_audio_message())

    assert enriched.text == "[Audio transcription]: Hola, estoy interesado en el departamento."
    assert enriched.audio["transcription_provider"] == "whisper_api"
    assert enriched.audio["transcription_status"] == "success"


@pytest.mark.asyncio
async def test_failure_fallback_is_added_when_provider_fails():
    settings = MessageBufferSettings(transcription_provider="whisper_api")
    service = AudioTranscriptionService(settings, provider=FakeFailureProvider())

    enriched = await service.enrich_message(make_audio_message())

    assert enriched.text == AUDIO_TRANSCRIPTION_FAILURE_PLACEHOLDER
    assert enriched.audio["transcription_provider"] == "whisper_api"
    assert enriched.audio["transcription_status"] == "failed"


@pytest.mark.asyncio
async def test_oversized_audio_uses_failure_fallback():
    settings = MessageBufferSettings(transcription_provider="whisper_api", max_audio_size_mb=1)
    oversized_message = make_audio_message().model_copy(
        update={
            "audio": {
                "base64": "aGVsbG8=",
                "mime_type": "audio/ogg",
                "file_length": 2 * 1024 * 1024,
            }
        }
    )
    service = AudioTranscriptionService(settings, provider=FakeSuccessProvider())

    enriched = await service.enrich_message(oversized_message)

    assert enriched.text == AUDIO_TRANSCRIPTION_FAILURE_PLACEHOLDER
    assert enriched.audio["transcription_status"] == "failed"


def test_format_audio_transcription_handles_empty_text():
    assert format_audio_transcription("") == AUDIO_TRANSCRIPTION_FAILURE_PLACEHOLDER

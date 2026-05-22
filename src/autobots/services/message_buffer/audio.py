"""Audio metadata and safe temporary-file helpers."""

from collections.abc import Mapping
from pathlib import Path
import base64
import binascii
import tempfile
from typing import Any

import httpx

from autobots.services.message_buffer.config import MessageBufferSettings


AUDIO_MESSAGE_KEYS = (
    "audioMessage",
    "pttMessage",
)

AUDIO_TRANSCRIPTION_PREFIX = "[Audio transcription]:"
AUDIO_TRANSCRIPTION_FAILURE_PLACEHOLDER = "[Voice message received but transcription failed]"


class AudioProcessingError(RuntimeError):
    """Base class for audio download and validation errors."""


class AudioTooLargeError(AudioProcessingError):
    """Raised when audio exceeds the configured maximum size."""


class AudioUnavailableError(AudioProcessingError):
    """Raised when no downloadable or embedded audio bytes are available."""


def find_audio_message(message: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Return the nested Evolution audio message payload when present."""
    for key in AUDIO_MESSAGE_KEYS:
        value = message.get(key)
        if isinstance(value, Mapping):
            return value
    return None


def extract_audio_reference(
    message: Mapping[str, Any],
    data: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Extract audio URL or media metadata from an Evolution message."""
    data = data or {}
    audio = find_audio_message(message)
    if not audio:
        return None

    media_url = (
        audio.get("url")
        or audio.get("mediaUrl")
        or data.get("mediaUrl")
        or data.get("media_url")
    )

    return {
        "url": media_url,
        "base64": audio.get("base64") or data.get("base64") or data.get("mediaBase64"),
        "direct_path": audio.get("directPath"),
        "media_key": audio.get("mediaKey"),
        "mime_type": audio.get("mimetype") or audio.get("mimeType"),
        "seconds": audio.get("seconds"),
        "ptt": audio.get("ptt"),
        "file_length": audio.get("fileLength"),
    }


def format_audio_transcription(text: str) -> str:
    """Return the user-visible buffer fragment for an audio transcription."""
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return AUDIO_TRANSCRIPTION_FAILURE_PLACEHOLDER
    return f"{AUDIO_TRANSCRIPTION_PREFIX} {cleaned}"


def get_declared_audio_size_bytes(audio: Mapping[str, Any]) -> int | None:
    """Return declared audio size from Evolution metadata when available."""
    raw_size = audio.get("file_length") or audio.get("fileLength")
    if raw_size is None:
        return None
    try:
        return int(raw_size)
    except (TypeError, ValueError):
        return None


def validate_audio_size(size_bytes: int, max_size_bytes: int) -> None:
    """Raise when an audio payload is larger than allowed."""
    if size_bytes > max_size_bytes:
        raise AudioTooLargeError("audio payload exceeds configured maximum size")


async def save_audio_to_temp_file(
    audio: Mapping[str, Any],
    settings: MessageBufferSettings,
) -> Path:
    """
    Download or decode audio into a temporary file.

    The caller owns the returned path and must delete it after use.
    """
    declared_size = get_declared_audio_size_bytes(audio)
    if declared_size is not None:
        validate_audio_size(declared_size, settings.max_audio_size_bytes)

    embedded_base64 = audio.get("base64")
    if embedded_base64:
        return _write_base64_audio_to_temp_file(str(embedded_base64), settings)

    url = audio.get("url")
    if not url:
        raise AudioUnavailableError("audio has no url or embedded base64 data")

    return await _download_audio_to_temp_file(str(url), settings)


def delete_temp_file(path: Path | None) -> None:
    """Best-effort deletion for temporary audio files."""
    if not path:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _write_base64_audio_to_temp_file(
    encoded_audio: str,
    settings: MessageBufferSettings,
) -> Path:
    raw_base64 = encoded_audio.split(",", maxsplit=1)[-1].strip()
    try:
        audio_bytes = base64.b64decode(raw_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise AudioUnavailableError("invalid embedded audio data") from exc

    validate_audio_size(len(audio_bytes), settings.max_audio_size_bytes)

    temp = tempfile.NamedTemporaryFile(delete=False, suffix=".audio")
    try:
        temp.write(audio_bytes)
        return Path(temp.name)
    finally:
        temp.close()


async def _download_audio_to_temp_file(
    url: str,
    settings: MessageBufferSettings,
) -> Path:
    total = 0
    temp = tempfile.NamedTemporaryFile(delete=False, suffix=".audio")
    temp_path = Path(temp.name)

    try:
        async with httpx.AsyncClient(timeout=settings.audio_download_timeout_seconds) as client:
            async with client.stream("GET", url, follow_redirects=True) as response:
                response.raise_for_status()

                content_length = response.headers.get("content-length")
                if content_length and content_length.isdigit():
                    validate_audio_size(int(content_length), settings.max_audio_size_bytes)

                async for chunk in response.aiter_bytes():
                    if not chunk:
                        continue
                    total += len(chunk)
                    validate_audio_size(total, settings.max_audio_size_bytes)
                    temp.write(chunk)

        return temp_path
    except Exception:
        delete_temp_file(temp_path)
        raise
    finally:
        temp.close()

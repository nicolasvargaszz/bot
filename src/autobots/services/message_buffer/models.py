"""Models and parsing helpers for the message buffer service."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import Enum
import hashlib
import re
from typing import Any

from pydantic import BaseModel, Field

from autobots.services.message_buffer.audio import extract_audio_reference


class MessageType(str, Enum):
    """Message types the buffer service understands."""

    TEXT = "text"
    AUDIO = "audio"
    UNSUPPORTED = "unsupported"


class IncomingMessage(BaseModel):
    """Normalized incoming message extracted from an Evolution webhook."""

    instance: str
    phone: str
    message_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    message_type: MessageType
    text: str | None = None
    audio: dict[str, Any] | None = None
    push_name: str | None = None

    @property
    def session_id(self) -> str:
        """Return the stable Redis session id for this contact."""
        return build_session_id(self.instance, self.phone)

    @property
    def deduplication_key(self) -> str:
        """Return the Redis key used to avoid duplicate message processing."""
        return RedisKeyBuilder.processed(self.message_id)

    def to_buffered_message(self) -> "BufferedMessage":
        """Convert an incoming message to the Redis-stored representation."""
        return BufferedMessage(
            instance=self.instance,
            phone=self.phone,
            message_id=self.message_id,
            timestamp=self.timestamp,
            message_type=self.message_type,
            text=normalize_text(self.text),
            audio=self.audio,
            push_name=self.push_name,
        )


class BufferedMessage(BaseModel):
    """Message fragment stored in Redis until the debounce window expires."""

    instance: str
    phone: str
    message_id: str
    timestamp: datetime
    message_type: MessageType
    text: str | None = None
    audio: dict[str, Any] | None = None
    push_name: str | None = None


class CombinedMessagePayload(BaseModel):
    """Payload sent to n8n after a sender's debounce window expires."""

    buffer_id: str
    instance: str
    phone: str
    push_name: str | None = None
    combined_text: str
    message_count: int
    event_ids: list[str]
    contains_audio: bool
    audio_messages: list[dict[str, Any]] = Field(default_factory=list)
    first_timestamp: datetime
    last_timestamp: datetime


class ParseResult(BaseModel):
    """Result of defensive Evolution payload parsing."""

    accepted: bool
    message: IncomingMessage | None = None
    reason: str | None = None


class RedisKeyBuilder:
    """Centralized Redis key construction."""

    active_sessions = "buffer:active_sessions"

    @staticmethod
    def buffer(session_id: str) -> str:
        return f"buffer:{session_id}"

    @staticmethod
    def timer(session_id: str) -> str:
        return f"timer:{session_id}"

    @staticmethod
    def meta(session_id: str) -> str:
        return f"meta:{session_id}"

    @staticmethod
    def lock(session_id: str) -> str:
        return f"lock:{session_id}"

    @staticmethod
    def processed(message_id: str) -> str:
        return f"processed:{sanitize_key_part(message_id)}"

    @staticmethod
    def failed(instance: str, phone: str, timestamp: int) -> str:
        return f"failed:{sanitize_key_part(instance)}:{sanitize_key_part(phone)}:{timestamp}"


class EvolutionWebhookParser:
    """Defensive parser for Evolution API webhook payloads."""

    @classmethod
    def parse(cls, payload: Mapping[str, Any]) -> ParseResult:
        root = cls._unwrap_body(payload)
        data = cls._as_mapping(root.get("data")) or root
        key = cls._as_mapping(data.get("key")) or {}
        message = cls._as_mapping(data.get("message")) or {}

        if key.get("fromMe") is True or data.get("fromMe") is True:
            return ParseResult(accepted=False, reason="message_from_self")

        remote_jid = (
            key.get("remoteJid")
            or data.get("remoteJid")
            or data.get("sender")
            or data.get("from")
        )
        if isinstance(remote_jid, str) and remote_jid.endswith("@g.us"):
            return ParseResult(accepted=False, reason="group_message_ignored")

        phone = normalize_phone(remote_jid)
        if not phone:
            return ParseResult(accepted=False, reason="missing_sender_phone")

        instance = str(
            root.get("instance")
            or data.get("instance")
            or data.get("instanceName")
            or "default"
        )

        message_id = str(
            key.get("id")
            or data.get("messageId")
            or data.get("id")
            or root.get("messageId")
            or ""
        ).strip()
        if not message_id:
            return ParseResult(accepted=False, reason="missing_message_id")

        text = cls._extract_text(message)
        audio = extract_audio_reference(message, data)
        message_type = cls._detect_message_type(text, audio)
        if message_type == MessageType.UNSUPPORTED:
            return ParseResult(accepted=False, reason="unsupported_message_type")

        incoming = IncomingMessage(
            instance=instance,
            phone=phone,
            message_id=message_id,
            timestamp=parse_timestamp(
                data.get("messageTimestamp")
                or data.get("timestamp")
                or root.get("date_time")
                or root.get("datetime")
            ),
            message_type=message_type,
            text=text,
            audio=audio,
            push_name=data.get("pushName") or data.get("push_name") or root.get("pushName"),
        )
        return ParseResult(accepted=True, message=incoming)

    @staticmethod
    def _unwrap_body(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        body = payload.get("body")
        if isinstance(body, Mapping):
            return body
        return payload

    @staticmethod
    def _as_mapping(value: Any) -> Mapping[str, Any] | None:
        if isinstance(value, Mapping):
            return value
        return None

    @staticmethod
    def _extract_text(message: Mapping[str, Any]) -> str | None:
        candidates = [
            message.get("conversation"),
            (message.get("extendedTextMessage") or {}).get("text")
            if isinstance(message.get("extendedTextMessage"), Mapping)
            else None,
            (message.get("imageMessage") or {}).get("caption")
            if isinstance(message.get("imageMessage"), Mapping)
            else None,
            (message.get("videoMessage") or {}).get("caption")
            if isinstance(message.get("videoMessage"), Mapping)
            else None,
        ]
        for candidate in candidates:
            text = normalize_text(candidate)
            if text:
                return text
        return None

    @staticmethod
    def _detect_message_type(text: str | None, audio: dict[str, Any] | None) -> MessageType:
        if text:
            return MessageType.TEXT
        if audio:
            return MessageType.AUDIO
        return MessageType.UNSUPPORTED


def combine_buffered_messages(messages: Sequence[BufferedMessage]) -> CombinedMessagePayload:
    """Combine buffered fragments into one n8n payload."""
    if not messages:
        raise ValueError("Cannot combine an empty message buffer")

    ordered = sorted(messages, key=lambda message: message.timestamp)
    text_parts = [normalize_text(message.text) for message in ordered]
    combined_text = " ".join(part for part in text_parts if part)
    audio_messages = [
        {
            "message_id": message.message_id,
            "timestamp": message.timestamp.isoformat(),
            "audio": message.audio,
        }
        for message in ordered
        if message.audio
    ]
    first = ordered[0]
    last = ordered[-1]
    event_ids = [message.message_id for message in ordered]

    return CombinedMessagePayload(
        buffer_id=build_buffer_id(first.instance, first.phone, event_ids),
        instance=first.instance,
        phone=first.phone,
        push_name=last.push_name or first.push_name,
        combined_text=combined_text,
        message_count=len(ordered),
        event_ids=event_ids,
        contains_audio=bool(audio_messages),
        audio_messages=audio_messages,
        first_timestamp=first.timestamp,
        last_timestamp=last.timestamp,
    )


def normalize_text(value: Any) -> str | None:
    """Normalize user-visible text fragments."""
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def normalize_phone(value: Any) -> str | None:
    """Extract a phone-like identifier from an Evolution JID or raw value."""
    if value is None:
        return None
    raw = str(value).split("@", maxsplit=1)[0]
    digits = re.sub(r"\D+", "", raw)
    return digits or None


def sanitize_key_part(value: Any) -> str:
    """Make a Redis key segment safe and readable."""
    cleaned = re.sub(r"[^A-Za-z0-9_.:-]+", "_", str(value or ""))
    return cleaned.strip("_") or "unknown"


def build_session_id(instance: str, phone: str) -> str:
    """Build the session id used by Redis key helpers."""
    return f"{sanitize_key_part(instance)}:{sanitize_key_part(phone)}"


def build_buffer_id(instance: str, phone: str, event_ids: Sequence[str]) -> str:
    """Build a deterministic idempotency id for a combined buffer."""
    raw = "|".join([instance, phone, *event_ids])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_timestamp(value: Any) -> datetime:
    """Parse Evolution timestamps defensively."""
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp, tz=UTC)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return datetime.now(UTC)
        if text.isdigit():
            return parse_timestamp(int(text))
        try:
            normalized = text.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return datetime.now(UTC)
    return datetime.now(UTC)

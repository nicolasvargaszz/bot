"""Error classification for the message buffer service.

The classes and helpers in this module describe what the system should do with
failures. They do not send alerts, write Redis records, or call external APIs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


AI_UNAVAILABLE_FALLBACK_MESSAGE = (
    "Gracias por escribir. En este momento estoy derivando tu consulta a una "
    "persona del equipo para ayudarte mejor."
)

TRANSCRIPTION_FAILED_FALLBACK_MESSAGE = (
    "[Voice message received but transcription failed]"
)


class ErrorCategory(str, Enum):
    """Known reliability categories for automation failures."""

    REDIS_UNAVAILABLE = "redis_unavailable"
    N8N_UNAVAILABLE = "n8n_unavailable"
    GEMINI_API_ERROR = "gemini_api_error"
    NOTION_API_ERROR = "notion_api_error"
    TELEGRAM_ERROR = "telegram_error"
    EVOLUTION_SESSION_DISCONNECTED = "evolution_session_disconnected"
    AUDIO_TRANSCRIPTION_FAILURE = "audio_transcription_failure"
    DUPLICATE_WEBHOOK_EVENT = "duplicate_webhook_event"
    MALFORMED_PAYLOAD = "malformed_payload"
    RATE_LIMITED_USER = "rate_limited_user"
    UNSUPPORTED_MEDIA = "unsupported_media"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ErrorHandlingPolicy:
    """Operational decision for an error category."""

    category: ErrorCategory
    retryable: bool
    alert_admin: bool
    silently_ignore: bool = False
    store_failed_message: bool = False
    fallback_message: str | None = None


class MessageBufferError(Exception):
    """Base exception for classified message buffer failures."""

    category = ErrorCategory.UNKNOWN

    def __init__(self, message: str = "", *, context: dict[str, object] | None = None):
        super().__init__(message or self.category.value)
        self.context = context or {}


class RedisUnavailableError(MessageBufferError):
    """Redis is down or cannot accept message buffer writes."""

    category = ErrorCategory.REDIS_UNAVAILABLE


class N8NUnavailableError(MessageBufferError):
    """n8n webhook delivery failed or n8n is unavailable."""

    category = ErrorCategory.N8N_UNAVAILABLE


class GeminiAPIError(MessageBufferError):
    """Gemini response generation or classification failed."""

    category = ErrorCategory.GEMINI_API_ERROR


class NotionAPIError(MessageBufferError):
    """Notion CRM update failed."""

    category = ErrorCategory.NOTION_API_ERROR


class TelegramDeliveryError(MessageBufferError):
    """Telegram admin/handoff alert failed."""

    category = ErrorCategory.TELEGRAM_ERROR


class EvolutionSessionDisconnectedError(MessageBufferError):
    """Evolution API WhatsApp session is disconnected."""

    category = ErrorCategory.EVOLUTION_SESSION_DISCONNECTED


class AudioTranscriptionError(MessageBufferError):
    """Audio transcription failed."""

    category = ErrorCategory.AUDIO_TRANSCRIPTION_FAILURE


class DuplicateWebhookEvent(MessageBufferError):
    """Webhook event was already processed."""

    category = ErrorCategory.DUPLICATE_WEBHOOK_EVENT


class MalformedPayloadError(MessageBufferError):
    """Webhook payload is malformed or missing required fields."""

    category = ErrorCategory.MALFORMED_PAYLOAD


class RateLimitedUserError(MessageBufferError):
    """A user sent too many messages in a short window."""

    category = ErrorCategory.RATE_LIMITED_USER


class UnsupportedMediaError(MessageBufferError):
    """The user sent media the automation does not support."""

    category = ErrorCategory.UNSUPPORTED_MEDIA


ERROR_POLICIES: dict[ErrorCategory, ErrorHandlingPolicy] = {
    ErrorCategory.REDIS_UNAVAILABLE: ErrorHandlingPolicy(
        category=ErrorCategory.REDIS_UNAVAILABLE,
        retryable=True,
        alert_admin=True,
        store_failed_message=True,
        fallback_message=AI_UNAVAILABLE_FALLBACK_MESSAGE,
    ),
    ErrorCategory.N8N_UNAVAILABLE: ErrorHandlingPolicy(
        category=ErrorCategory.N8N_UNAVAILABLE,
        retryable=True,
        alert_admin=True,
        store_failed_message=True,
    ),
    ErrorCategory.GEMINI_API_ERROR: ErrorHandlingPolicy(
        category=ErrorCategory.GEMINI_API_ERROR,
        retryable=True,
        alert_admin=True,
        store_failed_message=False,
        fallback_message=AI_UNAVAILABLE_FALLBACK_MESSAGE,
    ),
    ErrorCategory.NOTION_API_ERROR: ErrorHandlingPolicy(
        category=ErrorCategory.NOTION_API_ERROR,
        retryable=True,
        alert_admin=True,
        store_failed_message=False,
    ),
    ErrorCategory.TELEGRAM_ERROR: ErrorHandlingPolicy(
        category=ErrorCategory.TELEGRAM_ERROR,
        retryable=True,
        alert_admin=False,
        store_failed_message=False,
    ),
    ErrorCategory.EVOLUTION_SESSION_DISCONNECTED: ErrorHandlingPolicy(
        category=ErrorCategory.EVOLUTION_SESSION_DISCONNECTED,
        retryable=True,
        alert_admin=True,
        store_failed_message=True,
        fallback_message=AI_UNAVAILABLE_FALLBACK_MESSAGE,
    ),
    ErrorCategory.AUDIO_TRANSCRIPTION_FAILURE: ErrorHandlingPolicy(
        category=ErrorCategory.AUDIO_TRANSCRIPTION_FAILURE,
        retryable=False,
        alert_admin=False,
        store_failed_message=False,
        fallback_message=TRANSCRIPTION_FAILED_FALLBACK_MESSAGE,
    ),
    ErrorCategory.DUPLICATE_WEBHOOK_EVENT: ErrorHandlingPolicy(
        category=ErrorCategory.DUPLICATE_WEBHOOK_EVENT,
        retryable=False,
        alert_admin=False,
        silently_ignore=True,
        store_failed_message=False,
    ),
    ErrorCategory.MALFORMED_PAYLOAD: ErrorHandlingPolicy(
        category=ErrorCategory.MALFORMED_PAYLOAD,
        retryable=False,
        alert_admin=False,
        store_failed_message=False,
    ),
    ErrorCategory.RATE_LIMITED_USER: ErrorHandlingPolicy(
        category=ErrorCategory.RATE_LIMITED_USER,
        retryable=False,
        alert_admin=True,
        store_failed_message=True,
    ),
    ErrorCategory.UNSUPPORTED_MEDIA: ErrorHandlingPolicy(
        category=ErrorCategory.UNSUPPORTED_MEDIA,
        retryable=False,
        alert_admin=False,
        store_failed_message=False,
    ),
    ErrorCategory.UNKNOWN: ErrorHandlingPolicy(
        category=ErrorCategory.UNKNOWN,
        retryable=True,
        alert_admin=True,
        store_failed_message=True,
    ),
}


def get_error_policy(category: ErrorCategory) -> ErrorHandlingPolicy:
    """Return the handling policy for a category."""
    return ERROR_POLICIES.get(category, ERROR_POLICIES[ErrorCategory.UNKNOWN])


def classify_error(error: BaseException) -> ErrorHandlingPolicy:
    """Classify an exception into an operational handling policy."""
    if isinstance(error, MessageBufferError):
        return get_error_policy(error.category)
    return ERROR_POLICIES[ErrorCategory.UNKNOWN]


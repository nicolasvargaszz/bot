import pytest

from autobots.services.message_buffer.errors import (
    AI_UNAVAILABLE_FALLBACK_MESSAGE,
    AudioTranscriptionError,
    DuplicateWebhookEvent,
    ErrorCategory,
    GeminiAPIError,
    MalformedPayloadError,
    N8NUnavailableError,
    RedisUnavailableError,
    classify_error,
)
from autobots.services.message_buffer.retry import (
    RetryPolicy,
    calculate_backoff_delay,
    retry_delays,
    should_retry_error,
)


def test_exponential_backoff_is_capped():
    policy = RetryPolicy(
        max_attempts=5,
        base_delay_seconds=1,
        multiplier=2,
        max_delay_seconds=3,
    )

    assert calculate_backoff_delay(1, policy) == 1
    assert calculate_backoff_delay(2, policy) == 2
    assert calculate_backoff_delay(3, policy) == 3
    assert calculate_backoff_delay(4, policy) == 3


def test_retry_delays_returns_between_attempts_only():
    policy = RetryPolicy(max_attempts=4, base_delay_seconds=0.5, multiplier=2)

    assert retry_delays(policy) == [0.5, 1.0, 2.0]


def test_retryable_errors_retry_until_max_attempts():
    policy = RetryPolicy(max_attempts=3)
    error = RedisUnavailableError("redis down")

    assert should_retry_error(error, attempt=1, policy=policy)
    assert should_retry_error(error, attempt=2, policy=policy)
    assert not should_retry_error(error, attempt=3, policy=policy)


def test_non_retryable_errors_do_not_retry():
    policy = RetryPolicy(max_attempts=3)

    assert not should_retry_error(MalformedPayloadError("bad payload"), 1, policy)
    assert not should_retry_error(AudioTranscriptionError("bad audio"), 1, policy)


def test_duplicate_events_are_silent_and_not_retryable():
    policy = classify_error(DuplicateWebhookEvent("already processed"))

    assert policy.category == ErrorCategory.DUPLICATE_WEBHOOK_EVENT
    assert policy.silently_ignore
    assert not policy.retryable
    assert not policy.alert_admin


def test_ai_errors_have_human_handoff_fallback():
    policy = classify_error(GeminiAPIError("api unavailable"))

    assert policy.category == ErrorCategory.GEMINI_API_ERROR
    assert policy.retryable
    assert policy.alert_admin
    assert policy.fallback_message == AI_UNAVAILABLE_FALLBACK_MESSAGE


def test_n8n_errors_should_be_stored_and_alerted():
    policy = classify_error(N8NUnavailableError("n8n down"))

    assert policy.retryable
    assert policy.alert_admin
    assert policy.store_failed_message


def test_unknown_errors_are_retryable_and_alerted():
    policy = classify_error(RuntimeError("surprise"))

    assert policy.category == ErrorCategory.UNKNOWN
    assert policy.retryable
    assert policy.alert_admin


def test_retry_policy_rejects_invalid_values():
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=0)

    with pytest.raises(ValueError):
        calculate_backoff_delay(0)

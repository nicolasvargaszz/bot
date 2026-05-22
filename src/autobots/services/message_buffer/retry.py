"""Small retry helpers for message buffer dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from autobots.services.message_buffer.errors import classify_error


@dataclass(frozen=True)
class RetryPolicy:
    """Configuration for bounded exponential backoff."""

    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    multiplier: float = 2.0
    jitter_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_delay_seconds < 0:
            raise ValueError("base_delay_seconds must be non-negative")
        if self.max_delay_seconds < 0:
            raise ValueError("max_delay_seconds must be non-negative")
        if self.multiplier < 1:
            raise ValueError("multiplier must be at least 1")
        if self.jitter_seconds < 0:
            raise ValueError("jitter_seconds must be non-negative")


DEFAULT_RETRY_POLICY = RetryPolicy()


def calculate_backoff_delay(
    attempt: int,
    policy: RetryPolicy = DEFAULT_RETRY_POLICY,
) -> float:
    """
    Calculate delay before the next retry.

    `attempt` is 1-based and represents the attempt that just failed.
    """
    if attempt < 1:
        raise ValueError("attempt must be at least 1")

    raw_delay = policy.base_delay_seconds * (policy.multiplier ** (attempt - 1))
    capped_delay = min(raw_delay, policy.max_delay_seconds)
    return capped_delay + policy.jitter_seconds


def should_retry_error(
    error: BaseException,
    attempt: int,
    policy: RetryPolicy = DEFAULT_RETRY_POLICY,
) -> bool:
    """
    Decide whether an error should be retried after a failed attempt.

    `attempt` is 1-based and represents the attempt that just failed.
    """
    if attempt < 1:
        raise ValueError("attempt must be at least 1")
    if attempt >= policy.max_attempts:
        return False

    error_policy = classify_error(error)
    return error_policy.retryable and not error_policy.silently_ignore


def retry_delays(policy: RetryPolicy = DEFAULT_RETRY_POLICY) -> list[float]:
    """Return the sequence of delays between attempts."""
    return [
        calculate_backoff_delay(attempt, policy)
        for attempt in range(1, policy.max_attempts)
    ]


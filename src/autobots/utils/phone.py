"""Phone number helpers for Paraguay and WhatsApp links."""

import re
from typing import Optional


PARAGUAY_COUNTRY_CODE = "595"


def digits_only(value: object) -> str:
    """Return only numeric characters from a value."""
    return re.sub(r"\D+", "", str(value or ""))


def normalize_paraguay_phone_digits(phone: object) -> Optional[str]:
    """
    Normalize a Paraguay phone number to digits-only international format.

    Examples:
        0981 123 456 -> 595981123456
        +595 981 123 456 -> 595981123456
    """
    digits = digits_only(phone)
    if not digits:
        return None

    if digits.startswith("00"):
        digits = digits[2:]

    if digits.startswith("0"):
        digits = PARAGUAY_COUNTRY_CODE + digits[1:]
    elif not digits.startswith(PARAGUAY_COUNTRY_CODE):
        digits = PARAGUAY_COUNTRY_CODE + digits

    return digits


def is_valid_paraguay_phone(phone: object) -> bool:
    """Return True when the number looks usable for Paraguay WhatsApp links."""
    normalized = normalize_paraguay_phone_digits(phone)
    if not normalized or not normalized.startswith(PARAGUAY_COUNTRY_CODE):
        return False

    national_number = normalized[len(PARAGUAY_COUNTRY_CODE):]
    return 7 <= len(national_number) <= 9

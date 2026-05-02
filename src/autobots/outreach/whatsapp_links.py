"""Generate WhatsApp click-to-chat links without sending messages."""

from urllib.parse import quote

from autobots.utils.phone import normalize_paraguay_phone_digits


def encode_message(message: str) -> str:
    """URL-encode a WhatsApp message body."""
    return quote(message or "", safe="")


def generate_wa_me_link(phone: object, message: str | None = None) -> str:
    """
    Build a wa.me URL for manual outreach.

    This helper only creates a link. It does not send or automate messages.
    """
    normalized_phone = normalize_paraguay_phone_digits(phone)
    if not normalized_phone:
        raise ValueError("A valid phone number is required")

    url = f"https://wa.me/{normalized_phone}"
    if message:
        url = f"{url}?text={encode_message(message)}"
    return url

"""Generate WhatsApp click-to-chat links without sending messages."""

from typing import Mapping
from urllib.parse import quote

from autobots.leads.models import Lead
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


def generate_lead_whatsapp_link(lead: Lead | Mapping[str, object], message: str) -> str:
    """Generate a wa.me link for a processed lead or lead-like dictionary."""
    phone = lead.normalized_phone if isinstance(lead, Lead) else lead.get("normalized_phone")
    return generate_wa_me_link(phone, message)

"""Plain-text Telegram templates for human handoff alerts.

This module only formats message text. It does not send Telegram messages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from autobots.utils.phone import normalize_paraguay_phone_digits


HandoffCategory = Literal[
    "hot_lead",
    "wants_price",
    "wants_demo",
    "wants_human",
    "angry_confused_user",
    "spam_ignore",
    "needs_follow_up",
]


@dataclass(frozen=True)
class CategoryTemplate:
    """Default copy for one handoff category."""

    title: str
    urgency: str
    recommended_action: str


@dataclass(frozen=True)
class TelegramHandoff:
    """Data needed to generate a Telegram handoff alert."""

    category: HandoffCategory
    phone: str = ""
    lead_name: str | None = None
    niche: str = "unknown"
    client_account: str = "unknown"
    latest_combined_message: str = ""
    detected_intent: str = "unknown"
    lead_score: int | float | None = None
    urgency: str | None = None
    recommended_action: str | None = None
    suggested_manual_reply: str | None = None
    whatsapp_link: str | None = None
    crm_link: str | None = None


CATEGORY_TEMPLATES: dict[HandoffCategory, CategoryTemplate] = {
    "hot_lead": CategoryTemplate(
        title="HOT LEAD",
        urgency="high",
        recommended_action=(
            "Reply personally as soon as possible and move the conversation "
            "toward a call, demo, visit, or proposal."
        ),
    ),
    "wants_price": CategoryTemplate(
        title="WANTS PRICE",
        urgency="medium",
        recommended_action=(
            "Ask one or two qualifying questions before quoting, unless the "
            "correct price is already known."
        ),
    ),
    "wants_demo": CategoryTemplate(
        title="WANTS DEMO",
        urgency="high",
        recommended_action="Offer a short demo and propose a specific time.",
    ),
    "wants_human": CategoryTemplate(
        title="WANTS HUMAN",
        urgency="high",
        recommended_action=(
            "Take over manually and acknowledge that a person is now helping."
        ),
    ),
    "angry_confused_user": CategoryTemplate(
        title="ANGRY / CONFUSED USER",
        urgency="high",
        recommended_action="Apologize, keep the reply short, and take over manually.",
    ),
    "spam_ignore": CategoryTemplate(
        title="SPAM / IGNORE",
        urgency="low",
        recommended_action=(
            "Do not reply unless manual review finds a real business reason."
        ),
    ),
    "needs_follow_up": CategoryTemplate(
        title="NEEDS FOLLOW-UP",
        urgency="medium",
        recommended_action=(
            "Add a follow-up reminder and send a short manual message later."
        ),
    ),
}


def build_whatsapp_chat_link(phone: str | None) -> str | None:
    """Build a wa.me chat link from a phone number when possible."""
    normalized_phone = normalize_paraguay_phone_digits(phone)
    if not normalized_phone:
        return None
    return f"https://wa.me/{normalized_phone}"


def truncate_text(text: str | None, limit: int = 1200) -> str:
    """Trim long WhatsApp messages so Telegram alerts remain readable."""
    value = clean_value(text)
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."


def clean_value(value: object, fallback: str = "Unknown") -> str:
    """Convert a possibly empty value into compact display text."""
    text = " ".join(str(value or "").split())
    return text or fallback


def format_score(score: int | float | None) -> str:
    """Format lead score for display."""
    if score is None:
        return "Unknown"
    if isinstance(score, float) and score.is_integer():
        return str(int(score))
    return str(score)


def format_telegram_handoff(handoff: TelegramHandoff) -> str:
    """Generate a plain-text Telegram handoff alert."""
    template = CATEGORY_TEMPLATES[handoff.category]
    urgency = clean_value(handoff.urgency or template.urgency)
    recommended_action = clean_value(
        handoff.recommended_action or template.recommended_action
    )
    whatsapp_link = handoff.whatsapp_link or build_whatsapp_chat_link(handoff.phone)
    crm_link = handoff.crm_link or "Not available"

    lines = [
        f"[{template.title}]",
        "",
        f"Lead: {clean_value(handoff.lead_name)}",
        f"Phone: {clean_value(handoff.phone)}",
        f"Niche: {clean_value(handoff.niche)}",
        f"Account: {clean_value(handoff.client_account)}",
        f"Intent: {clean_value(handoff.detected_intent)}",
        f"Score: {format_score(handoff.lead_score)}",
        f"Urgency: {urgency}",
        "",
        "Latest message:",
        truncate_text(handoff.latest_combined_message),
        "",
        "Recommended action:",
        recommended_action,
        "",
        "Suggested manual reply:",
        truncate_text(handoff.suggested_manual_reply, limit=700),
        "",
        "Links:",
        f"WhatsApp: {whatsapp_link or 'Not available'}",
        f"CRM: {crm_link}",
    ]
    return "\n".join(lines)


def _message_for_category(category: HandoffCategory, **kwargs: object) -> str:
    """Build a Telegram alert for a specific category."""
    return format_telegram_handoff(TelegramHandoff(category=category, **kwargs))


def generate_hot_lead_message(**kwargs: object) -> str:
    """Generate a hot lead Telegram alert."""
    return _message_for_category("hot_lead", **kwargs)


def generate_wants_price_message(**kwargs: object) -> str:
    """Generate a wants price Telegram alert."""
    return _message_for_category("wants_price", **kwargs)


def generate_wants_demo_message(**kwargs: object) -> str:
    """Generate a wants demo Telegram alert."""
    return _message_for_category("wants_demo", **kwargs)


def generate_wants_human_message(**kwargs: object) -> str:
    """Generate a wants human Telegram alert."""
    return _message_for_category("wants_human", **kwargs)


def generate_angry_confused_user_message(**kwargs: object) -> str:
    """Generate an angry/confused user Telegram alert."""
    return _message_for_category("angry_confused_user", **kwargs)


def generate_spam_ignore_message(**kwargs: object) -> str:
    """Generate a spam/ignore Telegram alert."""
    return _message_for_category("spam_ignore", **kwargs)


def generate_needs_follow_up_message(**kwargs: object) -> str:
    """Generate a needs follow-up Telegram alert."""
    return _message_for_category("needs_follow_up", **kwargs)


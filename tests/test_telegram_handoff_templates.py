from autobots.handoff.telegram_templates import (
    build_whatsapp_chat_link,
    generate_angry_confused_user_message,
    generate_hot_lead_message,
    generate_needs_follow_up_message,
    generate_spam_ignore_message,
    generate_wants_demo_message,
    generate_wants_human_message,
    generate_wants_price_message,
)


BASE_PAYLOAD = {
    "lead_name": "Juan Perez",
    "phone": "0981 123 456",
    "niche": "real_estate",
    "client_account": "Autobots Demo",
    "latest_combined_message": "Hola Nico, me interesa. Cuanto cuesta?",
    "detected_intent": "wants_price",
    "lead_score": 88,
    "suggested_manual_reply": "Hola Juan, te puedo mostrar una demo corta hoy.",
    "crm_link": "https://notion.so/example",
}


def test_build_whatsapp_chat_link_normalizes_paraguay_phone():
    assert build_whatsapp_chat_link("0981 123 456") == "https://wa.me/595981123456"


def test_hot_lead_template_includes_required_context():
    message = generate_hot_lead_message(**BASE_PAYLOAD)

    assert "[HOT LEAD]" in message
    assert "Lead: Juan Perez" in message
    assert "Phone: 0981 123 456" in message
    assert "Niche: real_estate" in message
    assert "Account: Autobots Demo" in message
    assert "Intent: wants_price" in message
    assert "Score: 88" in message
    assert "Urgency: high" in message
    assert "Latest message:" in message
    assert "Recommended action:" in message
    assert "Suggested manual reply:" in message
    assert "WhatsApp: https://wa.me/595981123456" in message
    assert "CRM: https://notion.so/example" in message


def test_price_template_uses_default_medium_urgency():
    message = generate_wants_price_message(**BASE_PAYLOAD)

    assert "[WANTS PRICE]" in message
    assert "Urgency: medium" in message
    assert "Ask one or two qualifying questions" in message


def test_all_category_helpers_generate_expected_titles():
    generators = [
        (generate_wants_demo_message, "[WANTS DEMO]"),
        (generate_wants_human_message, "[WANTS HUMAN]"),
        (generate_angry_confused_user_message, "[ANGRY / CONFUSED USER]"),
        (generate_spam_ignore_message, "[SPAM / IGNORE]"),
        (generate_needs_follow_up_message, "[NEEDS FOLLOW-UP]"),
    ]

    for generator, title in generators:
        assert title in generator(**BASE_PAYLOAD)


def test_template_uses_fallbacks_for_missing_optional_values():
    message = generate_spam_ignore_message(phone="")

    assert "Lead: Unknown" in message
    assert "Phone: Unknown" in message
    assert "WhatsApp: Not available" in message
    assert "CRM: Not available" in message

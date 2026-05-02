from autobots.outreach.whatsapp_links import generate_wa_me_link
from autobots.utils.phone import is_valid_paraguay_phone, normalize_paraguay_phone_digits


def test_normalize_paraguay_mobile_number():
    assert normalize_paraguay_phone_digits("0981 123 456") == "595981123456"
    assert normalize_paraguay_phone_digits("+595 981 123 456") == "595981123456"


def test_validate_paraguay_phone_number():
    assert is_valid_paraguay_phone("0981 123 456")
    assert not is_valid_paraguay_phone("123")


def test_generate_whatsapp_link_does_not_send_messages():
    link = generate_wa_me_link("0981 123 456", "Hola, podemos hablar?")

    assert link == "https://wa.me/595981123456?text=Hola%2C%20podemos%20hablar%3F"

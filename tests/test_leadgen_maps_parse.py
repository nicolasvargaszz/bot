"""Unit tests for the pure parse/score layer of the lead-gen Maps scraper."""

from autobots.scrapers.leadgen_maps import (
    dedup_key,
    load_seen,
    parse_card,
    score_lead,
)


def make_raw(**overrides) -> dict:
    raw = {
        "aria_name": "Clínica Santa Clara",
        "href": "https://www.google.com/maps/place/data=!4m2!3m1!1s0xabc",
        "rating_text": "4,6",
        "reviews_text": "(1.234)",
        "phone_text": "0981 123 456",
        "has_website_link": False,
        "info_lines": ["Clínica · Av. España 1234", "Abierto · Cierra a las 18"],
    }
    raw.update(overrides)
    return raw


def test_parse_card_full_record():
    lead = parse_card(make_raw(), "clínica médica", "Asunción", "clinica")

    assert lead["name"] == "Clínica Santa Clara"
    assert lead["phone"] == "595981123456"
    assert lead["phone_is_mobile"] is True
    assert lead["rating"] == 4.6
    assert lead["review_count"] == 1234
    assert lead["category"] == "Clínica"
    assert lead["has_website"] is False
    assert lead["niche"] == "clinica"


def test_parse_card_landline_is_not_mobile():
    lead = parse_card(
        make_raw(phone_text="(021) 555 123"), "farmacia", "San Lorenzo", "farmacia"
    )
    assert lead["phone"] == "59521555123"
    assert lead["phone_is_mobile"] is False


def test_parse_card_without_name_is_rejected():
    assert parse_card(make_raw(aria_name="  "), "óptica", "Asunción", "optica") is None


def test_parse_card_without_phone_keeps_address_lead():
    lead = parse_card(make_raw(phone_text=""), "sanatorio", "Asunción", "sanatorio")
    assert lead is not None
    assert lead["phone"] is None


def test_category_skips_open_closed_status_lines():
    raw = make_raw(info_lines=["Abierto · Cierra a las 18", "Farmacia · Ruta 2 km 20"])
    lead = parse_card(raw, "farmacia", "San Lorenzo", "farmacia")
    assert lead["category"] == "Farmacia"


def test_score_prefers_high_volume_reachable_business():
    hot = parse_card(make_raw(), "clínica médica", "Asunción", "clinica")
    cold = parse_card(
        make_raw(reviews_text="(3)", phone_text="", has_website_link=True),
        "mueblería", "Fernando de la Mora", "muebleria",
    )
    assert score_lead(hot) > score_lead(cold)
    assert 0 <= score_lead(cold) <= 100
    assert 0 <= score_lead(hot) <= 100


def test_dedup_key_prefers_phone_over_href():
    lead = parse_card(make_raw(), "clínica médica", "Asunción", "clinica")
    assert dedup_key(lead) == "595981123456"

    no_phone = parse_card(make_raw(phone_text=""), "clínica médica", "Asunción", "clinica")
    assert dedup_key(no_phone).startswith("https://www.google.com/maps/place/")


def test_load_seen_resumes_from_jsonl(tmp_path):
    path = tmp_path / "leads.jsonl"
    lead = parse_card(make_raw(), "clínica médica", "Asunción", "clinica")
    path.write_text(
        "\n".join([__import__("json").dumps(lead), "{not json"]) + "\n",
        encoding="utf-8",
    )
    seen = load_seen(path)
    assert "595981123456" in seen

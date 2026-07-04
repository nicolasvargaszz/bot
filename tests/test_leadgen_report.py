"""Tests for the lead-gen Markdown report builder."""

from datetime import date

from autobots.outreach.leadgen_report import build_report, contact_cell


def make_lead(**overrides) -> dict:
    lead = {
        "name": "Clínica Santa Clara",
        "niche": "clinica",
        "rating": 4.6,
        "review_count": 1234,
        "phone": "595981123456",
        "phone_is_mobile": True,
        "has_website": False,
        "score": 86,
    }
    lead.update(overrides)
    return lead


def test_contact_cell_mobile_gets_wa_link_with_opener():
    cell = contact_cell(make_lead())
    assert cell.startswith("[WhatsApp directo](https://wa.me/595981123456?text=")


def test_contact_cell_landline_and_missing_phone():
    assert contact_cell(make_lead(phone="59521555123", phone_is_mobile=False)) == "llamar +59521555123"
    assert "sin teléfono" in contact_cell(make_lead(phone=None))


def test_build_report_ranks_by_score():
    report = build_report(
        [make_lead(name="Frío", score=20, review_count=3),
         make_lead(name="Caliente", score=90)],
        today=date(2026, 7, 3),
    )
    assert report.index("Caliente") < report.index("Frío")
    assert "2 negocios" in report
    assert "| Clínicas / centros médicos | 2 |" in report

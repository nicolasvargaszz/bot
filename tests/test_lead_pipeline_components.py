from autobots.leads.cleaner import clean_leads
from autobots.leads.models import Lead
from autobots.leads.pipeline import process_records
from autobots.leads.scorer import score_lead
from autobots.outreach.message_generator import generate_outreach_message
from autobots.outreach.whatsapp_links import generate_lead_whatsapp_link


def test_duplicate_removal_by_normalized_phone():
    records = [
        {"name": "Inmobiliaria Uno", "phone": "0981 123 456"},
        {"name": "Inmobiliaria Duplicada", "phone": "+595 981 123 456"},
        {"name": "Inmobiliaria Dos", "phone": "0992 111 222"},
    ]

    leads = clean_leads(records)

    assert [lead.name for lead in leads] == ["Inmobiliaria Uno", "Inmobiliaria Dos"]


def test_score_real_estate_lead_is_high_priority_when_fit_is_strong():
    lead = Lead(
        name="ABC Inmobiliaria",
        phone="0981 123 456",
        normalized_phone="595981123456",
        category="Inmobiliaria",
        city="Asunción",
        source_url="https://maps.example/abc",
        rating=4.7,
        review_count=45,
        has_website=False,
    )

    result = score_lead(lead, "real_estate")

    assert result.score >= 75
    assert result.priority == "high"
    assert "category matches real_estate" in result.reasons


def test_generate_real_estate_message_mentions_business_outcome():
    lead = Lead(name="ABC Inmobiliaria")

    message = generate_outreach_message(lead, "real_estate")

    assert "ABC Inmobiliaria" in message
    assert "WhatsApp" in message
    assert "filtrar interesados" in message


def test_generate_lead_whatsapp_link_encodes_message():
    lead = Lead(normalized_phone="595981123456")

    link = generate_lead_whatsapp_link(lead, "Hola, podemos hablar?")

    assert link == "https://wa.me/595981123456?text=Hola%2C%20podemos%20hablar%3F"


def test_process_records_outputs_required_fields_sorted_by_score():
    records = [
        {
            "name": "Tienda Random",
            "phone": "0981 000 111",
            "category": "Tienda de ropa",
            "city": "Asunción",
            "reviews": "8",
            "has_website": "no",
        },
        {
            "name": "Sin Teléfono",
            "phone": "",
            "category": "Tienda de ropa",
            "city": "Asunción",
        },
    ]

    processed = process_records(records, "retail")

    assert processed[0].name == "Tienda Random"
    assert processed[0].normalized_phone == "595981000111"
    assert processed[0].whatsapp_link.startswith("https://wa.me/595981000111")
    assert processed[0].status == "new"
    assert processed[1].status == "invalid_phone"

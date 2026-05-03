"""Lead cleaning helpers for raw CSV and JSON exports."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from autobots.leads.models import Lead
from autobots.utils.phone import is_valid_paraguay_phone, normalize_paraguay_phone_digits


FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name", "nombre", "business_name", "negocio", "title", "place_name"),
    "phone": ("phone", "telefono", "teléfono", "whatsapp", "mobile", "phone_number"),
    "category": ("category", "categoria", "categoría", "type", "tipo", "business_category"),
    "city": ("city", "ciudad", "locality", "location", "zona"),
    "source_url": (
        "source_url",
        "google_maps",
        "google_maps_url",
        "maps_url",
        "place_url",
        "url",
        "link",
    ),
    "rating": ("rating", "calificacion", "calificación", "stars"),
    "review_count": ("review_count", "reviews", "reseñas", "reviewCount", "reviews_count"),
    "website_url": ("website_url", "website", "web", "site", "sitio_web"),
    "has_website": ("has_website", "tiene_web", "hasWebsite"),
}


def clean_text(value: object) -> str:
    """Return a compact string without leading, trailing, or repeated spaces."""
    return " ".join(str(value or "").strip().split())


def get_first_value(record: Mapping[str, Any], aliases: Iterable[str]) -> Any:
    """Return the first non-empty value from known field aliases."""
    for alias in aliases:
        if alias in record and record[alias] not in (None, ""):
            return record[alias]
    return ""


def parse_float(value: object) -> float | None:
    """Parse a float from scraper data, accepting commas as decimal separators."""
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def parse_int(value: object) -> int | None:
    """Parse an integer from scraper data."""
    if value in (None, ""):
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if not digits:
        return None
    return int(digits)


def parse_bool(value: object) -> bool | None:
    """Parse common truthy and falsy values from scraped fields."""
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value

    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "si", "sí", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    return None


def normalize_source_url(record: Mapping[str, Any]) -> str:
    """Build a useful source URL from known fields."""
    source_url = clean_text(get_first_value(record, FIELD_ALIASES["source_url"]))
    if source_url:
        return source_url

    place_id = clean_text(record.get("google_place_id") or record.get("place_id"))
    if place_id:
        return f"https://www.google.com/maps/place/?q=place_id:{place_id}"

    return ""


def clean_lead(record: Mapping[str, Any]) -> Lead:
    """Convert a raw scraper row into a normalized Lead."""
    phone = clean_text(get_first_value(record, FIELD_ALIASES["phone"]))
    normalized_phone = normalize_paraguay_phone_digits(phone) or ""
    if normalized_phone and not is_valid_paraguay_phone(normalized_phone):
        normalized_phone = ""

    website_url = clean_text(get_first_value(record, FIELD_ALIASES["website_url"]))
    parsed_has_website = parse_bool(get_first_value(record, FIELD_ALIASES["has_website"]))
    has_website = bool(website_url) if parsed_has_website is None else parsed_has_website

    return Lead(
        name=clean_text(get_first_value(record, FIELD_ALIASES["name"])),
        phone=phone,
        normalized_phone=normalized_phone,
        category=clean_text(get_first_value(record, FIELD_ALIASES["category"])),
        city=clean_text(get_first_value(record, FIELD_ALIASES["city"])) or "Asunción",
        source_url=normalize_source_url(record),
        rating=parse_float(get_first_value(record, FIELD_ALIASES["rating"])),
        review_count=parse_int(get_first_value(record, FIELD_ALIASES["review_count"])),
        website_url=website_url,
        has_website=has_website,
        raw=dict(record),
    )


def remove_duplicate_leads(leads: Iterable[Lead]) -> list[Lead]:
    """
    Remove duplicates by normalized phone.

    The first valid phone wins. Leads without a normalized phone are kept because
    their status can still explain why they were not prepared for WhatsApp.
    """
    unique: list[Lead] = []
    seen_phones: set[str] = set()

    for lead in leads:
        if not lead.normalized_phone:
            unique.append(lead)
            continue
        if lead.normalized_phone in seen_phones:
            continue
        seen_phones.add(lead.normalized_phone)
        unique.append(lead)

    return unique


def clean_leads(records: Iterable[Mapping[str, Any]]) -> list[Lead]:
    """Clean and deduplicate raw lead records."""
    return remove_duplicate_leads(clean_lead(record) for record in records)

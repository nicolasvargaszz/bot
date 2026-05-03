"""Data models for lead processing and outreach preparation."""

from dataclasses import dataclass, field
from typing import Any, Literal


Niche = Literal["real_estate", "retail", "clinics", "beauty"]

SUPPORTED_NICHES: tuple[Niche, ...] = (
    "real_estate",
    "retail",
    "clinics",
    "beauty",
)


@dataclass(slots=True)
class Lead:
    """Normalized lead record used by the processing pipeline."""

    name: str = ""
    phone: str = ""
    normalized_phone: str = ""
    category: str = ""
    city: str = ""
    source_url: str = ""
    rating: float | None = None
    review_count: int | None = None
    website_url: str = ""
    has_website: bool | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def has_valid_phone(self) -> bool:
        return bool(self.normalized_phone)


@dataclass(slots=True)
class LeadScore:
    """Scoring result for a lead."""

    score: int
    priority: str
    reasons: list[str] = field(default_factory=list)

    @property
    def reasons_text(self) -> str:
        return "; ".join(self.reasons)


@dataclass(slots=True)
class ProcessedLead:
    """Final lead shape exported to CSV."""

    name: str
    phone: str
    normalized_phone: str
    category: str
    city: str
    source_url: str
    score: int
    priority: str
    score_reasons: str
    suggested_message: str
    whatsapp_link: str
    status: str = "new"

    def to_row(self) -> dict[str, object]:
        return {
            "name": self.name,
            "phone": self.phone,
            "normalized_phone": self.normalized_phone,
            "category": self.category,
            "city": self.city,
            "source_url": self.source_url,
            "score": self.score,
            "priority": self.priority,
            "score_reasons": self.score_reasons,
            "suggested_message": self.suggested_message,
            "whatsapp_link": self.whatsapp_link,
            "status": self.status,
        }


OUTPUT_FIELDS: list[str] = [
    "name",
    "phone",
    "normalized_phone",
    "category",
    "city",
    "source_url",
    "score",
    "priority",
    "score_reasons",
    "suggested_message",
    "whatsapp_link",
    "status",
]

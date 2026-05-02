"""
Business Analysis Agent - Scoring & Qualification System
Target Market: Paraguay (Asunción)

This agent evaluates scraped businesses and decides if they are worth contacting.
No UI, no outreach - pure analysis and qualification.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import json
import logging

logger = logging.getLogger(__name__)


# ===========================================
# ENUMS & CONSTANTS
# ===========================================

class Decision(Enum):
    GO = "go"
    NO_GO = "no_go"
    REVIEW = "manual_review"


class CustomerType(Enum):
    B2C_LOCAL = "b2c_local"           # Consumers in neighborhood
    B2C_CITYWIDE = "b2c_citywide"     # Consumers across city
    B2B_LOCAL = "b2b_local"           # Other businesses
    MIXED = "mixed"                    # Both B2B and B2C
    TOURIST = "tourist"                # Tourist-focused


class WebsiteStructure(Enum):
    SINGLE_PAGE = "single_page"        # Simple landing page
    MULTI_PAGE_BASIC = "multi_page_basic"  # 3-5 pages
    CATALOG = "catalog"                # Products/services showcase
    BOOKING = "booking"                # With reservation system
    PORTFOLIO = "portfolio"            # Work showcase


# Category weights for Paraguay market
CATEGORY_WEIGHTS = {
    "restaurant": 1.3,
    "cafe": 1.2,
    "salon": 1.4,       # High demand in Asunción
    "barber": 1.3,
    "dental": 1.5,      # Professional services convert well
    "medical": 1.4,
    "automotive": 1.2,
    "retail": 1.0,
    "bakery": 1.1,
    "veterinary": 1.3,
    "gym": 1.1,
    "real_estate": 1.5,
    "legal": 1.4,
    "spa": 1.3,
    "florist": 1.0,
    "pharmacy": 0.7,    # Usually have websites already
    "generic": 0.8,
}

# Location tiers for Paraguay
LOCATION_TIERS = {
    "asuncion_centro": 1.0,
    "villa_morra": 1.2,        # High-end area
    "carmelitas": 1.1,
    "san_lorenzo": 0.9,
    "luque": 0.85,
    "lambare": 0.9,
    "fernando_de_la_mora": 0.85,
    "mariano_roque_alonso": 0.8,
    "default": 0.75,
}


# ===========================================
# DATA CLASSES
# ===========================================

@dataclass
class BusinessInput:
    """Input data from scraper"""
    id: str
    name: str
    category: str
    address: str
    city: str = "Asunción"
    neighborhood: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    rating: float = 0.0
    review_count: int = 0
    photo_count: int = 0
    has_website: bool = False
    existing_website: Optional[str] = None
    hours: Optional[dict] = None
    raw_data: Optional[dict] = None


@dataclass
class ScoreBreakdown:
    """Detailed score components"""
    review_score: float = 0.0
    rating_score: float = 0.0
    photo_score: float = 0.0
    category_score: float = 0.0
    location_score: float = 0.0
    contact_score: float = 0.0
    activity_score: float = 0.0
    
    @property
    def total(self) -> float:
        return round(
            self.review_score + 
            self.rating_score + 
            self.photo_score + 
            self.category_score + 
            self.location_score + 
            self.contact_score +
            self.activity_score
        , 2)
    
    def to_dict(self) -> dict:
        return {
            "review_score": self.review_score,
            "rating_score": self.rating_score,
            "photo_score": self.photo_score,
            "category_score": self.category_score,
            "location_score": self.location_score,
            "contact_score": self.contact_score,
            "activity_score": self.activity_score,
            "total": self.total
        }


@dataclass
class AnalysisResult:
    """Complete analysis output"""
    business_id: str
    
    # Scores
    total_score: float
    score_breakdown: ScoreBreakdown
    
    # Profile
    profile_summary: str
    customer_type: CustomerType
    
    # Recommendations
    website_necessity_score: float  # 0-100
    recommended_structure: WebsiteStructure
    recommended_pages: list = field(default_factory=list)
    
    # Decision
    decision: Decision
    decision_reasons: list = field(default_factory=list)
    
    # Metadata
    analyzed_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> dict:
        return {
            "business_id": self.business_id,
            "total_score": self.total_score,
            "score_breakdown": self.score_breakdown.to_dict(),
            "profile_summary": self.profile_summary,
            "customer_type": self.customer_type.value,
            "website_necessity_score": self.website_necessity_score,
            "recommended_structure": self.recommended_structure.value,
            "recommended_pages": self.recommended_pages,
            "decision": self.decision.value,
            "decision_reasons": self.decision_reasons,
            "analyzed_at": self.analyzed_at.isoformat()
        }


# ===========================================
# ANALYSIS AGENT
# ===========================================

class BusinessAnalyzer:
    """
    Main Analysis Agent
    
    Evaluates businesses and produces GO/NO-GO decisions
    with detailed scoring and recommendations.
    """
    
    # Thresholds
    MIN_SCORE_GO = 50
    MIN_SCORE_REVIEW = 35
    MIN_REVIEWS_QUALIFIED = 3
    
    def __init__(self):
        self.category_weights = CATEGORY_WEIGHTS
        self.location_tiers = LOCATION_TIERS
    
    def analyze(self, business: BusinessInput) -> AnalysisResult:
        """Main analysis entry point"""
        
        # Skip if already has website
        if business.has_website and business.existing_website:
            return self._create_no_go_result(
                business, 
                ["Business already has a website"]
            )
        
        # Calculate scores
        breakdown = self._calculate_scores(business)
        
        # Determine customer type
        customer_type = self._determine_customer_type(business)
        
        # Calculate website necessity
        necessity_score = self._calculate_website_necessity(business, breakdown)
        
        # Recommend website structure
        structure, pages = self._recommend_structure(business, customer_type)
        
        # Generate profile summary
        profile = self._generate_profile_summary(business, customer_type)
        
        # Make decision
        decision, reasons = self._make_decision(business, breakdown, necessity_score)
        
        return AnalysisResult(
            business_id=business.id,
            total_score=breakdown.total,
            score_breakdown=breakdown,
            profile_summary=profile,
            customer_type=customer_type,
            website_necessity_score=necessity_score,
            recommended_structure=structure,
            recommended_pages=pages,
            decision=decision,
            decision_reasons=reasons
        )
    
    def _calculate_scores(self, b: BusinessInput) -> ScoreBreakdown:
        """Calculate all score components (max 100 total)"""
        
        breakdown = ScoreBreakdown()
        
        # Review score (0-20 points)
        # More reviews = established business
        if b.review_count >= 50:
            breakdown.review_score = 20
        elif b.review_count >= 20:
            breakdown.review_score = 15
        elif b.review_count >= 10:
            breakdown.review_score = 12
        elif b.review_count >= 5:
            breakdown.review_score = 8
        elif b.review_count >= 1:
            breakdown.review_score = 4
        
        # Rating score (0-15 points)
        if b.rating >= 4.5:
            breakdown.rating_score = 15
        elif b.rating >= 4.0:
            breakdown.rating_score = 12
        elif b.rating >= 3.5:
            breakdown.rating_score = 8
        elif b.rating >= 3.0:
            breakdown.rating_score = 4
        
        # Photo score (0-10 points)
        # Photos indicate business cares about presence
        if b.photo_count >= 10:
            breakdown.photo_score = 10
        elif b.photo_count >= 5:
            breakdown.photo_score = 7
        elif b.photo_count >= 1:
            breakdown.photo_score = 4
        
        # Category score (0-25 points)
        category_key = b.category.lower().replace(" ", "_")
        weight = self.category_weights.get(category_key, 0.8)
        breakdown.category_score = round(25 * weight / 1.5, 2)  # Normalize
        
        # Location score (0-15 points)
        location_key = self._get_location_key(b.neighborhood, b.city)
        loc_weight = self.location_tiers.get(location_key, 0.75)
        breakdown.location_score = round(15 * loc_weight, 2)
        
        # Contact info score (0-10 points)
        if b.phone and b.email:
            breakdown.contact_score = 10
        elif b.phone:
            breakdown.contact_score = 7
        elif b.email:
            breakdown.contact_score = 5
        
        # Activity score (0-5 points)
        # Based on hours and other indicators
        if b.hours:
            breakdown.activity_score = 5
        
        return breakdown
    
    def _determine_customer_type(self, b: BusinessInput) -> CustomerType:
        """Determine primary customer type"""
        
        category = b.category.lower()
        
        # Tourist-focused
        if b.neighborhood in ["centro_historico", "loma_san_jeronimo"]:
            if category in ["restaurant", "cafe", "hotel"]:
                return CustomerType.TOURIST
        
        # B2B focused
        if category in ["legal", "accounting", "real_estate"]:
            return CustomerType.B2B_LOCAL
        
        # Citywide B2C
        if category in ["dental", "medical", "spa", "gym"]:
            return CustomerType.B2C_CITYWIDE
        
        # Mixed
        if category in ["automotive", "veterinary"]:
            return CustomerType.MIXED
        
        # Default: Local B2C
        return CustomerType.B2C_LOCAL
    
    def _calculate_website_necessity(
        self, 
        b: BusinessInput, 
        scores: ScoreBreakdown
    ) -> float:
        """Calculate how much this business needs a website (0-100)"""
        
        necessity = 50.0  # Base
        
        # High reviews but no website = high necessity
        if b.review_count >= 20:
            necessity += 15
        elif b.review_count >= 10:
            necessity += 10
        
        # Good rating = more to show off
        if b.rating >= 4.0:
            necessity += 10
        
        # Category factor
        category = b.category.lower()
        high_necessity_cats = ["dental", "medical", "legal", "real_estate", "salon"]
        if category in high_necessity_cats:
            necessity += 15
        
        # Location factor (premium areas need online presence)
        if b.neighborhood in ["villa_morra", "carmelitas"]:
            necessity += 10
        
        # Cap at 100
        return min(necessity, 100)
    
    def _recommend_structure(
        self, 
        b: BusinessInput, 
        customer_type: CustomerType
    ) -> tuple[WebsiteStructure, list]:
        """Recommend website structure and pages"""
        
        category = b.category.lower()
        
        # Default pages
        base_pages = ["Inicio", "Servicios", "Contacto"]
        
        # Restaurant/Cafe
        if category in ["restaurant", "cafe", "bakery"]:
            return WebsiteStructure.SINGLE_PAGE, [
                "Inicio con menú destacado",
                "Galería de platos",
                "Ubicación y horarios",
                "WhatsApp directo"
            ]
        
        # Salon/Barber/Spa
        if category in ["salon", "barber", "spa"]:
            return WebsiteStructure.BOOKING, [
                "Inicio",
                "Servicios y precios",
                "Galería de trabajos",
                "Reservar cita",
                "Contacto"
            ]
        
        # Professional services
        if category in ["dental", "medical", "legal", "accounting"]:
            return WebsiteStructure.MULTI_PAGE_BASIC, [
                "Inicio",
                "Servicios",
                "Sobre nosotros",
                "Testimonios",
                "Contacto/Agendar"
            ]
        
        # Retail
        if category in ["retail", "florist", "pharmacy"]:
            return WebsiteStructure.CATALOG, [
                "Inicio",
                "Productos",
                "Ofertas",
                "Contacto"
            ]
        
        # Default
        return WebsiteStructure.SINGLE_PAGE, base_pages
    
    def _generate_profile_summary(
        self, 
        b: BusinessInput, 
        customer_type: CustomerType
    ) -> str:
        """Generate a brief profile summary"""
        
        rating_text = f"{b.rating}/5" if b.rating else "sin calificación"
        review_text = f"{b.review_count} reseñas" if b.review_count else "sin reseñas"
        
        customer_text = {
            CustomerType.B2C_LOCAL: "clientes locales del barrio",
            CustomerType.B2C_CITYWIDE: "clientes de toda la ciudad",
            CustomerType.B2B_LOCAL: "empresas y profesionales",
            CustomerType.MIXED: "clientes particulares y empresas",
            CustomerType.TOURIST: "turistas y visitantes"
        }.get(customer_type, "clientes varios")
        
        return (
            f"{b.name} es un negocio de {b.category} ubicado en "
            f"{b.neighborhood or b.city}. Tiene {rating_text} con {review_text}. "
            f"Su público principal son {customer_text}."
        )
    
    def _make_decision(
        self, 
        b: BusinessInput, 
        scores: ScoreBreakdown, 
        necessity: float
    ) -> tuple[Decision, list]:
        """Make GO/NO-GO decision with reasons"""
        
        reasons = []
        total = scores.total
        
        # Automatic NO-GO conditions
        if b.has_website:
            return Decision.NO_GO, ["Ya tiene sitio web"]
        
        if b.review_count == 0 and b.rating == 0:
            reasons.append("Sin actividad en Google Maps")
            return Decision.NO_GO, reasons
        
        # Score-based decision
        if total >= self.MIN_SCORE_GO:
            reasons.append(f"Score alto: {total}/100")
            
            if b.review_count >= 10:
                reasons.append(f"Negocio establecido ({b.review_count} reseñas)")
            
            if b.rating >= 4.0:
                reasons.append(f"Buena reputación ({b.rating}/5)")
            
            if necessity >= 70:
                reasons.append("Alta necesidad de presencia web")
            
            return Decision.GO, reasons
        
        elif total >= self.MIN_SCORE_REVIEW:
            reasons.append(f"Score moderado: {total}/100")
            reasons.append("Requiere revisión manual")
            return Decision.REVIEW, reasons
        
        else:
            reasons.append(f"Score bajo: {total}/100")
            if b.review_count < self.MIN_REVIEWS_QUALIFIED:
                reasons.append("Pocas reseñas - negocio nuevo o inactivo")
            return Decision.NO_GO, reasons
    
    def _get_location_key(
        self, 
        neighborhood: Optional[str], 
        city: str
    ) -> str:
        """Get location tier key"""
        if neighborhood:
            key = neighborhood.lower().replace(" ", "_")
            if key in self.location_tiers:
                return key
        return "default"
    
    def _create_no_go_result(
        self, 
        b: BusinessInput, 
        reasons: list
    ) -> AnalysisResult:
        """Create a NO-GO result quickly"""
        return AnalysisResult(
            business_id=b.id,
            total_score=0,
            score_breakdown=ScoreBreakdown(),
            profile_summary=f"{b.name} - No califica",
            customer_type=CustomerType.B2C_LOCAL,
            website_necessity_score=0,
            recommended_structure=WebsiteStructure.SINGLE_PAGE,
            recommended_pages=[],
            decision=Decision.NO_GO,
            decision_reasons=reasons
        )


# ===========================================
# DATABASE STORAGE
# ===========================================

def store_analysis_result(result: AnalysisResult, db_connection) -> None:
    """
    Store analysis result in database.
    
    Updates the businesses table with:
    - score
    - score_breakdown (JSONB)
    - status (qualified/low_priority)
    - analyzed_at
    
    SQL executed:
    
    UPDATE businesses SET
        score = :total_score,
        score_breakdown = :breakdown_json,
        status = :new_status,
        analyzed_at = NOW()
    WHERE id = :business_id
    """
    
    new_status = {
        Decision.GO: "qualified",
        Decision.REVIEW: "manual_review", 
        Decision.NO_GO: "low_priority"
    }.get(result.decision, "low_priority")
    
    # This would use SQLAlchemy or asyncpg
    query = """
        UPDATE businesses SET
            score = $1,
            score_breakdown = $2,
            status = $3,
            analyzed_at = NOW()
        WHERE id = $4
    """
    
    # Execute: db_connection.execute(query, params)
    logger.info(
        f"Stored analysis for {result.business_id}: "
        f"score={result.total_score}, decision={result.decision.value}"
    )


# ===========================================
# EXAMPLE USAGE
# ===========================================

if __name__ == "__main__":
    # Example business from Asunción
    example_business = BusinessInput(
        id="biz_001",
        name="Peluquería Elegance",
        category="salon",
        address="Av. Mariscal López 1234",
        city="Asunción",
        neighborhood="villa_morra",
        phone="+595 21 123456",
        email=None,
        rating=4.6,
        review_count=28,
        photo_count=15,
        has_website=False
    )
    
    analyzer = BusinessAnalyzer()
    result = analyzer.analyze(example_business)
    
    print("\n" + "="*50)
    print("ANALYSIS RESULT")
    print("="*50)
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))

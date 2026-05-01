"""
Discovery Agent - Google Maps Scraper
Target: Paraguay (Asunción, Gran Asunción, Central)

Extracts business data from Google Maps and identifies
businesses without an official website.
"""

import asyncio
import json
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from playwright.async_api import async_playwright, Page, Browser, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[3]


# ===========================================
# CONSTANTS
# ===========================================

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

SOCIAL_MEDIA_DOMAINS = [
    "facebook.com", "fb.com", "fb.me",
    "instagram.com", "instagr.am",
    "twitter.com", "x.com",
    "tiktok.com",
    "linkedin.com",
    "wa.me", "whatsapp.com",
    "youtube.com", "youtu.be",
]

# Selectors for Google Maps (updated January 2026 - ULTRA Deep Data Extraction)
SELECTORS = {
    "search_input": '#UGojuc, input.UGojuc, input[name="q"]',
    "search_button": 'button.mL3xi, button[aria-label="Búsqueda"], button[aria-label="Search"]',
    "results_container": 'div[role="feed"], div.m6QErb.DxyBCb',
    "result_item": 'a.hfpxzc',
    "result_card": 'div.Nv2PK',
    # Detail panel selectors
    "business_name": 'h1.DUwDvf, div.qBF1Pd.fontHeadlineSmall',
    "rating_stars": 'span.ZkP5Je',  # aria-label="4,6 estrellas 206 reseñas"
    "rating_value": 'span.MW4etd',  # "4,6"
    "review_count": 'div.fontBodySmall',  # "236 reseñas"
    "review_count_alt": 'span.UY7F9',   # "(206)" - fallback
    "category": 'button[jsaction*="category"], button.DkEaL',
    "address": 'button[data-item-id="address"] div.Io6YTe, button[data-item-id="address"], div.rogA2c',
    "phone": 'button[data-item-id*="phone"], a[href^="tel:"]',
    "website": 'a[data-item-id="authority"]',
    
    # === PRICE DATA ===
    "price_range": 'span.mgr77e span, span.mgr77e',
    "price_per_person": 'div.MNVeJb div',  # "₲ 20.000-40.000 por persona"
    "price_voters": 'div.BfVpR',  # "Notificado por 79 personas"
    "price_histogram": 'table[aria-label*="Histograma"] tr',  # Price distribution rows
    "price_histogram_range": 'td.fsAi0e',  # "₲ 20.000-40.000"
    "price_histogram_percent": 'span.xYsBQe',  # style="width: 42%;"
    
    # === SERVICE OPTIONS ===
    "service_options": 'div.E0DTEd div.LTs0Rc[role="group"], div.LTs0Rc[aria-label]',
    "accessibility": 'span.wmQCje[aria-label]',  # "Accesible con silla de ruedas"
    
    # === OPENING HOURS ===
    "hours_table": 'table.eK4R0e tbody tr.y0skZc',
    "hours_row_day": 'td.ylH6lf div',
    "hours_row_time": 'td.mxowUb',
    "open_status": 'span.ZDu9vd span',  # "Cerrado" / "Abierto"
    
    # === POPULAR TIMES (HORAS PUNTA) ===
    "popular_times_container": 'div.UmE4Qe[aria-label*="Horas punta"]',
    "popular_times_bars": 'div.dpoVLd[role="img"]',  # aria-label="Nivel de ocupación: 57 % (hora: 12 p. m.)"
    "popular_times_day_selector": 'button.e2moi span.uEubGf',  # "domingos"
    
    # === THIRD-PARTY LINKS ===
    "order_link": 'a[data-item-id="action:4"]',
    "menu_link": 'a[data-item-id="menu"], button[aria-label="Carta"]',
    "reserve_link": 'a[data-item-id="reserve"], a[aria-label*="reserva"]',
    
    # === PLUS CODE ===
    "plus_code": 'button[data-item-id="oloc"] div.Io6YTe',  # "MCX9+73 Asunción"
    
    # === PHOTO CATEGORIES ===
    "photo_categories": 'div.fp2VUc button.K4UgGe',  # aria-label="Carta", "Ambiente", etc.
    "photo_category_label": 'span.zaTlhd',  # Label text inside photo buttons
    
    # === REVIEW TOPICS/KEYWORDS ===
    "review_topics": 'div[role="radiogroup"] button.e2moi[aria-label]',  # "sandwiches, mencionado en 15 reseñas"
    "review_topic_count": 'span.bC3Nkc',  # " 15" count inside topic button
    
    # === RATING DISTRIBUTION ===
    "rating_distribution": 'tr.BHOKXe',  # aria-label="5 estrellas, 196 reseñas"
    
    # === INDIVIDUAL REVIEWS ===
    "review_cards": 'div.jftiEf[data-review-id]',
    "review_author": 'div.d4r55',  # Reviewer name
    "review_author_info": 'div.RfnDt',  # "Local Guide · 70 reseñas · 519 fotos"
    "review_author_avatar": 'img.NBa7we',  # Author profile photo
    "review_author_profile": 'button.al6Kxe[data-href]',  # Profile link button
    "review_rating": 'span.kvMYJc',  # aria-label="5 estrellas"
    "review_date": 'span.rsqaWe',  # "Hace 2 meses"
    "review_text": 'span.wiI7pd',  # Review content
    "review_photos": 'button.Tya61d',  # Review photo buttons (background-image style)
    "review_expand": 'button.w8nwRe',  # "Más" button to expand review
    
    # === CUSTOMER UPDATES ===
    "customer_updates": 'button.wjCxie',  # Customer update cards
    "update_text": 'div.ZXMsO',  # Update text content
    "update_date": 'div.jrtH8d',  # "Hace un año"
    
    # === INFORMATION TAB (Business Attributes) ===
    "info_tab": 'button[aria-label*="Información sobre"]',  # Tab button
    "info_section": 'div.iP2t7d.fontBodyMedium',  # Each attribute section
    "info_section_title": 'h2.iL3Qke.fontTitleSmall',  # Section title (Accesibilidad, Pagos, etc.)
    "info_items_list": 'ul.ZQ6we',  # Items list
    "info_item": 'li.hpLkke',  # Individual item
    "info_item_text": 'span[aria-label]',  # Item text with aria-label
}


# ===========================================
# DATA CLASSES
# ===========================================

@dataclass
class ScrapedBusiness:
    """Raw business data from Google Maps - ULTRA Deep Data Version"""
    name: str
    google_place_id: Optional[str] = None
    category: Optional[str] = None
    address: Optional[str] = None
    city: str = "Asunción"
    neighborhood: Optional[str] = None
    phone: Optional[str] = None
    rating: float = 0.0
    review_count: int = 0  # FIX: Track review count explicitly
    photo_urls: list = field(default_factory=list)
    photo_count: int = 0
    
    # Website detection
    has_website: bool = False
    website_url: Optional[str] = None
    website_status: str = "none"  # none, social_only, dead, active
    
    # FIX 5: About/Description from Google
    about_summary: Optional[str] = None  # Business description from "About" section
    
    # Price Data
    price_range: Optional[str] = None  # e.g., "₲ 20.000-40.000"
    price_level: int = 0  # 1-4 ($, $$, $$$, $$$$)
    price_per_person: Optional[str] = None  # "₲ 20.000-40.000 por persona"
    price_voters: int = 0  # "Notificado por 79 personas"
    price_histogram: dict = field(default_factory=dict)  # {"₲ 1-20.000": 0, "₲ 20.000-40.000": 42, ...}
    
    # Service options
    service_options: dict = field(default_factory=dict)  # {dine_in, takeout, delivery}
    accessibility: list = field(default_factory=list)  # ["wheelchair_accessible", ...]
    
    # Business Attributes from "Información" tab
    offerings: list = field(default_factory=list)  # ["Café", ...]
    dining_options: list = field(default_factory=list)  # ["Desayunos", ...]
    amenities: list = field(default_factory=list)  # ["Sanitario", ...]
    planning: list = field(default_factory=list)  # ["Visita rápida", ...]
    payments: list = field(default_factory=list)  # ["Tarjetas de crédito", "NFC", ...]
    parking: list = field(default_factory=list)  # ["Estacionamiento gratuito", ...]
    
    # Opening hours - structured
    opening_hours: dict = field(default_factory=dict)  # {"monday": "07:00-20:00", ...}
    is_open_now: Optional[bool] = None
    open_status_text: Optional[str] = None  # "Cerrado · Abre a las 7 a. m. del lun"
    
    # Popular Times (Horas Punta) - hourly busyness by day
    popular_times: dict = field(default_factory=dict)  # {"monday": {"6": 0, "7": 14, ...}, ...}
    
    # Third-party links
    order_link: Optional[str] = None  # PedidosYa, UberEats, etc.
    order_provider: Optional[str] = None  # "pedidosya", "ubereats", etc.
    menu_link: Optional[str] = None
    reserve_link: Optional[str] = None
    
    # Social media (separate from website)
    social_media: dict = field(default_factory=dict)  # {instagram, facebook, tiktok}
    
    # Plus Code for precise location
    plus_code: Optional[str] = None  # "MCX9+73 Asunción"
    
    # Photo Categories
    photo_categories: list = field(default_factory=list)  # ["Carta", "Ambiente", "Comida y bebida", ...]
    
    # Review Topics/Keywords mentioned in reviews
    review_topics: dict = field(default_factory=dict)  # {"sandwiches": 15, "calidad": 13, "café": 9, ...}
    
    # Rating Distribution
    rating_distribution: dict = field(default_factory=dict)  # {"5": 196, "4": 25, "3": 8, "2": 2, "1": 5}
    
    # Top Reviews (actual customer reviews)
    reviews: list = field(default_factory=list)  # [{"author", "rating", "text", "date", "photos"}, ...]
    
    # Customer Updates (posts from the business or customers)
    customer_updates: list = field(default_factory=list)  # [{"text", "date"}, ...]
    
    # Metadata
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    scraped_at: datetime = field(default_factory=datetime.utcnow)
    raw_data: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "google_place_id": self.google_place_id,
            "category": self.category,
            "address": self.address,
            "city": self.city,
            "neighborhood": self.neighborhood,
            "phone": self.phone,
            "rating": self.rating,
            "review_count": self.review_count,  # FIX: Include review count
            "photo_urls": self.photo_urls,
            "photo_count": self.photo_count,
            "has_website": self.has_website,
            "website_url": self.website_url,
            "website_status": self.website_status,
            # About/Description
            "about_summary": self.about_summary,  # FIX 5: About section
            # Price Data
            "price_range": self.price_range,
            "price_level": self.price_level,
            "price_per_person": self.price_per_person,
            "price_voters": self.price_voters,
            "price_histogram": self.price_histogram,
            # Services & Accessibility
            "service_options": self.service_options,
            "accessibility": self.accessibility,
            # Business Attributes
            "offerings": self.offerings,
            "dining_options": self.dining_options,
            "amenities": self.amenities,
            "planning": self.planning,
            "payments": self.payments,
            "parking": self.parking,
            # Hours & Status
            "opening_hours": self.opening_hours,
            "is_open_now": self.is_open_now,
            "open_status_text": self.open_status_text,
            # Popular Times
            "popular_times": self.popular_times,
            # Third-party Links
            "order_link": self.order_link,
            "order_provider": self.order_provider,
            "menu_link": self.menu_link,
            "reserve_link": self.reserve_link,
            # Social Media
            "social_media": self.social_media,
            # Location
            "plus_code": self.plus_code,
            "latitude": self.latitude,
            "longitude": self.longitude,
            # Photos
            "photo_categories": self.photo_categories,
            # Reviews & Topics
            "review_topics": self.review_topics,
            "rating_distribution": self.rating_distribution,
            "reviews": self.reviews,
            # Updates
            "customer_updates": self.customer_updates,
            # Meta
            "scraped_at": self.scraped_at.isoformat(),
        }


# ===========================================
# MAPS SCRAPER CLASS
# ===========================================

class MapsScraper:
    """
    Google Maps Scraper for discovering businesses without websites.
    
    Uses Playwright for browser automation with anti-detection measures.
    """
    
    def __init__(
        self,
        headless: bool = True,
        delay_min: float = 2.0,
        delay_max: float = 5.0,
        max_results_per_search: int = 60,
        timeout: int = 30000,
    ):
        self.headless = headless
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.max_results = max_results_per_search
        self.timeout = timeout
        
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.results: list[ScrapedBusiness] = []
        
        # Load locations config
        self.locations = self._load_locations()
        self.categories = self._load_categories()
    
    def _load_locations(self) -> dict:
        """Load locations from config file"""
        config_path = PACKAGE_ROOT / "config" / "locations.json"
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning(f"Locations config not found at {config_path}")
            return {"cities": []}
    
    def _load_categories(self) -> dict:
        """Load categories from config file"""
        config_path = PACKAGE_ROOT / "config" / "categories.json"
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning(f"Categories config not found at {config_path}")
            return {}
    
    async def _random_delay(self, multiplier: float = 1.0) -> None:
        """Add random delay to avoid detection"""
        delay = random.uniform(self.delay_min, self.delay_max) * multiplier
        await asyncio.sleep(delay)
    
    def _get_random_user_agent(self) -> str:
        """Get random user agent string"""
        return random.choice(USER_AGENTS)
    
    def _is_social_media_url(self, url: str) -> bool:
        """Check if URL is a social media profile"""
        if not url:
            return False
        try:
            domain = urlparse(url).netloc.lower().replace("www.", "")
            return any(social in domain for social in SOCIAL_MEDIA_DOMAINS)
        except Exception:
            return False
    
    def _classify_social_media(self, url: str) -> Optional[str]:
        """Classify which social media platform a URL belongs to"""
        if not url:
            return None
        url_lower = url.lower()
        if "instagram.com" in url_lower or "instagr.am" in url_lower:
            return "instagram"
        elif "facebook.com" in url_lower or "fb.com" in url_lower or "fb.me" in url_lower:
            return "facebook"
        elif "tiktok.com" in url_lower:
            return "tiktok"
        elif "twitter.com" in url_lower or "x.com" in url_lower:
            return "twitter"
        elif "youtube.com" in url_lower or "youtu.be" in url_lower:
            return "youtube"
        elif "linkedin.com" in url_lower:
            return "linkedin"
        elif "wa.me" in url_lower or "whatsapp.com" in url_lower:
            return "whatsapp"
        return None
    
    def _clean_price_range(self, text: str) -> str:
        """Clean price range text removing hidden characters and normalizing"""
        if not text:
            return ""
        # Remove non-breaking spaces and other hidden chars
        cleaned = text.replace('\xa0', ' ').replace('\u200b', '').strip()
        # Normalize spaces
        cleaned = ' '.join(cleaned.split())
        return cleaned
    
    def _estimate_price_level(self, price_text: str) -> int:
        """Estimate price level (1-4) from price range text"""
        if not price_text:
            return 0
        # Count currency symbols or check for ranges
        dollar_count = price_text.count('$') + price_text.count('₲')
        if dollar_count >= 4:
            return 4
        elif dollar_count >= 3:
            return 3
        elif dollar_count >= 2:
            return 2
        elif dollar_count >= 1:
            return 1
        
        # Try to parse numeric range for Guaraníes
        numbers = re.findall(r'[\d\.]+', price_text.replace('.', ''))
        if numbers:
            try:
                max_price = max(int(n) for n in numbers if n)
                if max_price > 200000:
                    return 4
                elif max_price > 100000:
                    return 3
                elif max_price > 50000:
                    return 2
                else:
                    return 1
            except (ValueError, TypeError):
                pass
        return 0
    
    def _parse_hours_text(self, day: str, time_text: str) -> tuple[str, str]:
        """Parse day and time text into normalized format"""
        # Normalize day names to English keys
        day_map = {
            'lunes': 'monday', 'monday': 'monday',
            'martes': 'tuesday', 'tuesday': 'tuesday',
            'miércoles': 'wednesday', 'miercoles': 'wednesday', 'wednesday': 'wednesday',
            'jueves': 'thursday', 'thursday': 'thursday',
            'viernes': 'friday', 'friday': 'friday',
            'sábado': 'saturday', 'sabado': 'saturday', 'saturday': 'saturday',
            'domingo': 'sunday', 'sunday': 'sunday',
        }
        
        day_key = day_map.get(day.lower().strip(), day.lower().strip())
        
        # Handle "Cerrado" / "Closed"
        if 'cerrado' in time_text.lower() or 'closed' in time_text.lower():
            return day_key, 'closed'
        
        # Handle "Abierto 24 horas" / "Open 24 hours"
        if '24' in time_text and ('hora' in time_text.lower() or 'hour' in time_text.lower()):
            return day_key, '00:00-24:00'
        
        # Parse time range like "7 a. m. a 8 p. m." or "7:00-20:00"
        time_text = time_text.strip()
        
        # Try to extract start and end times
        # Pattern for "7 a. m. a 8 p. m." format
        am_pm_pattern = r'(\d{1,2})(?::(\d{2}))?\s*(?:a\.?\s*m\.?|AM)\s*(?:a|to|-|–)\s*(\d{1,2})(?::(\d{2}))?\s*(?:p\.?\s*m\.?|PM)'
        match = re.search(am_pm_pattern, time_text, re.IGNORECASE)
        if match:
            start_h = int(match.group(1))
            start_m = match.group(2) or '00'
            end_h = int(match.group(3)) + 12  # PM
            end_m = match.group(4) or '00'
            return day_key, f"{start_h:02d}:{start_m}-{end_h:02d}:{end_m}"
        
        # Pattern for "7:00 - 20:00" format
        time_24_pattern = r'(\d{1,2}):(\d{2})\s*(?:a|to|-|–)\s*(\d{1,2}):(\d{2})'
        match = re.search(time_24_pattern, time_text)
        if match:
            return day_key, f"{int(match.group(1)):02d}:{match.group(2)}-{int(match.group(3)):02d}:{match.group(4)}"
        
        # Return original if can't parse
        return day_key, time_text
    
    def _parse_popular_times_label(self, aria_label: str) -> tuple[int, int]:
        """Parse popular times from aria-label like 'Nivel de ocupación: 57 % (hora: 12 p. m.)'"""
        if not aria_label:
            return 0, 0
        
        # Extract percentage
        percent_match = re.search(r'(\d+)\s*%', aria_label)
        percent = int(percent_match.group(1)) if percent_match else 0
        
        # Extract hour
        hour_match = re.search(r'hora:\s*(\d+)\s*(a\.?\s*m\.?|p\.?\s*m\.?)', aria_label, re.IGNORECASE)
        if hour_match:
            hour = int(hour_match.group(1))
            period = hour_match.group(2).lower().replace('.', '').replace(' ', '')
            if 'pm' in period and hour != 12:
                hour += 12
            elif 'am' in period and hour == 12:
                hour = 0
            return hour, percent
        
        return 0, percent
    
    def _parse_review_topic(self, aria_label: str) -> tuple[str, int]:
        """Parse review topic from aria-label like 'sandwiches, mencionado en 15 reseñas'"""
        if not aria_label:
            return "", 0
        
        # Pattern: "topic, mencionado en N reseñas"
        match = re.search(r'^([^,]+),?\s*mencionado en\s*(\d+)', aria_label, re.IGNORECASE)
        if match:
            return match.group(1).strip(), int(match.group(2))
        return aria_label, 0
    
    def _parse_rating_distribution(self, aria_label: str) -> tuple[int, int]:
        """Parse rating from aria-label like '5 estrellas, 196 reseñas'"""
        if not aria_label:
            return 0, 0
        
        stars_match = re.search(r'(\d+)\s*estrellas?', aria_label)
        count_match = re.search(r'(\d+)\s*rese\u00f1as?', aria_label)
        
        stars = int(stars_match.group(1)) if stars_match else 0
        count = int(count_match.group(1)) if count_match else 0
        
        return stars, count
    
    def _classify_order_provider(self, url: str) -> str:
        """Classify which delivery service a URL belongs to"""
        if not url:
            return ""
        url_lower = url.lower()
        if "pedidosya" in url_lower:
            return "pedidosya"
        elif "ubereats" in url_lower:
            return "ubereats"
        elif "rappi" in url_lower:
            return "rappi"
        elif "deliveroo" in url_lower:
            return "deliveroo"
        elif "doordash" in url_lower:
            return "doordash"
        return "other"
    
    def _extract_place_id(self, url: str) -> Optional[str]:
        """Extract Google Place ID from URL"""
        if not url:
            return None
        # Pattern: /maps/place/.../data=...!1s0x...
        match = re.search(r'!1s(0x[a-f0-9]+:[a-f0-9]+)', url)
        if match:
            return match.group(1)
        # Alternative pattern: place_id=...
        match = re.search(r'place_id=([^&]+)', url)
        if match:
            return match.group(1)
        return None
    
    def _parse_review_count(self, text: str) -> int:
        """Parse review count from text like '(123)' or '123 reseñas'"""
        if not text:
            return 0
        numbers = re.findall(r'[\d,\.]+', text.replace(".", "").replace(",", ""))
        if numbers:
            try:
                return int(numbers[0])
            except ValueError:
                return 0
        return 0
    
    def _parse_rating(self, text: str) -> float:
        """Parse rating from text like '4.5' or '4,5'"""
        if not text:
            return 0.0
        text = text.replace(",", ".")
        match = re.search(r'(\d+\.?\d*)', text)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return 0.0
        return 0.0
    
    async def initialize(self) -> None:
        """Initialize browser with anti-detection settings"""
        playwright = await async_playwright().start()
        
        self.browser = await playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-web-security',
                '--lang=es-PY,es',
            ]
        )
        
        context = await self.browser.new_context(
            user_agent=self._get_random_user_agent(),
            viewport={"width": 1920, "height": 1080},
            locale="es-PY",
            timezone_id="America/Asuncion",
            geolocation={"latitude": -25.2637, "longitude": -57.5759},
            permissions=["geolocation"],
        )
        
        # Anti-detection scripts
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            window.chrome = {runtime: {}};
        """)
        
        self.page = await context.new_page()
        self.page.set_default_timeout(self.timeout)
        
        logger.info("Browser initialized with anti-detection measures")
    
    async def close(self) -> None:
        """Close browser"""
        if self.browser:
            await self.browser.close()
            logger.info("Browser closed")
    
    async def search_businesses(
        self,
        query: str,
        location: str,
        max_results: Optional[int] = None
    ) -> list[ScrapedBusiness]:
        """
        Search for businesses on Google Maps.
        
        Args:
            query: Search term (e.g., "restaurantes", "salón de belleza")
            location: Location to search (e.g., "Villa Morra, Asunción")
            max_results: Maximum results to scrape
            
        Returns:
            List of ScrapedBusiness objects
        """
        if not self.page:
            await self.initialize()
        
        max_results = max_results or self.max_results
        search_query = f"{query} en {location}, Paraguay"
        
        logger.info(f"Searching: {search_query}")
        
        try:
            # Navigate to Google Maps
            await self.page.goto("https://www.google.com/maps?hl=es", wait_until="domcontentloaded")
            await self._random_delay(1.0)
            
            # Handle cookie consent - try multiple button variations
            for selector in [
                'button[aria-label*="Aceptar"]',
                'button[aria-label*="Accept"]', 
                'button:has-text("Aceptar todo")',
                'button:has-text("Accept all")',
                'form[action*="consent"] button',
                'button#L2AGLb',
            ]:
                try:
                    btn = await self.page.query_selector(selector)
                    if btn:
                        await btn.click()
                        logger.info("Accepted cookie consent")
                        await self._random_delay(0.5)
                        break
                except Exception:
                    continue
            
            # Perform search
            search_box = await self.page.wait_for_selector(SELECTORS["search_input"], timeout=10000)
            await search_box.click()
            await self._random_delay(0.3)
            await search_box.fill(search_query)
            await self._random_delay(0.3)
            
            # Click search button or press Enter
            search_btn = await self.page.query_selector(SELECTORS["search_button"])
            if search_btn:
                await search_btn.click()
            else:
                await self.page.keyboard.press("Enter")
            
            await self._random_delay(1.5)
            
            # Wait for results panel to appear (left sidebar with business list)
            try:
                await self.page.wait_for_selector(SELECTORS["results_container"], timeout=10000)
            except PlaywrightTimeout:
                # If no results panel, try scrollable container
                try:
                    await self.page.wait_for_selector('div.m6QErb.WNBkOb', timeout=5000)
                except PlaywrightTimeout:
                    logger.warning("Results panel not found, checking for map pins...")
            
            await self._random_delay()
            
            # Scroll to load more results
            businesses = await self._scroll_and_collect_results(max_results)
            
            # Process each business
            results = []
            for i, business_el in enumerate(businesses[:max_results]):
                try:
                    business = await self._extract_business_details(business_el, location)
                    if business:
                        results.append(business)
                        logger.info(f"[{i+1}/{len(businesses)}] Scraped: {business.name}")
                    
                    await self._random_delay(0.5)
                    
                except Exception as e:
                    logger.warning(f"Error extracting business {i}: {e}")
                    continue
            
            self.results.extend(results)
            return results
            
        except PlaywrightTimeout:
            # Save screenshot for debugging
            await self.page.screenshot(path="debug_timeout.png")
            logger.error(f"Timeout searching for: {search_query}. Screenshot saved.")
            return []
        except Exception as e:
            logger.error(f"Error during search: {e}")
            return []
    
    async def _scroll_and_collect_results(self, target_count: int) -> list:
        """Scroll through results to load more businesses
        
        Google Maps loads results lazily as you scroll. We need to:
        1. Scroll down in the results panel
        2. Wait for new results to load
        3. Repeat until we have enough results or hit the end
        """
        # Try multiple selectors for the scrollable container
        results_container = None
        container_selectors = [
            'div[role="feed"]',
            'div.m6QErb.DxyBCb.kA9KIf.dS8AEf.XiKgde',
            'div.m6QErb.DxyBCb',
            'div.m6QErb.WNBkOb',
            'div.m6QErb',
        ]
        
        for selector in container_selectors:
            results_container = await self.page.query_selector(selector)
            if results_container:
                logger.debug(f"Found results container with selector: {selector}")
                break
        
        if not results_container:
            logger.warning("Results container not found")
            return []
        
        collected = []
        seen_hrefs = set()
        last_count = 0
        no_change_count = 0
        max_no_change = 8  # Increased: Allow more attempts before giving up
        scroll_amount = 800  # Increased: Scroll more pixels at once
        
        logger.info(f"📜 Starting scroll to collect up to {target_count} businesses...")
        
        while len(collected) < target_count and no_change_count < max_no_change:
            # Get current results - links to places
            items = await self.page.query_selector_all('a.hfpxzc')
            
            # Deduplicate by href
            for item in items:
                href = await item.get_attribute("href")
                if href and href not in seen_hrefs:
                    seen_hrefs.add(href)
                    collected.append(item)
            
            current_count = len(collected)
            
            if current_count == last_count:
                no_change_count += 1
                # If stuck, try scrolling more aggressively
                if no_change_count >= 3:
                    scroll_amount = 1500  # Scroll even more
            else:
                no_change_count = 0
                last_count = current_count
            
            # Check if we've reached the end of results (look for "end of list" indicators)
            end_marker = await self.page.query_selector('span.HlvSq, div.PbZDve')
            if end_marker:
                end_text = await end_marker.inner_text() if end_marker else ""
                if "fin" in end_text.lower() or "end" in end_text.lower() or "no hay más" in end_text.lower():
                    logger.info(f"📍 Reached end of results at {current_count} businesses")
                    break
            
            # Scroll down in the container
            try:
                await results_container.evaluate(f"el => el.scrollBy(0, {scroll_amount})")
            except Exception:
                # If scrolling fails, try scrolling the whole page
                await self.page.evaluate(f"window.scrollBy(0, {scroll_amount})")
            
            # Wait for new content to load (important!)
            await self._random_delay(0.6)
            
            # Every 5 scrolls, wait a bit longer to let more content load
            if no_change_count > 0 and no_change_count % 2 == 0:
                await self._random_delay(1.0)
            
            logger.debug(f"📜 Scrolling... found {current_count} unique results (attempt {no_change_count}/{max_no_change})")
        
        logger.info(f"✅ Collected {len(collected)} business links (target was {target_count})")
        return collected[:target_count]
    
    async def _extract_business_details(self, element, location: str) -> Optional[ScrapedBusiness]:
        """Extract details from a business listing - ULTRA DEEP DATA VERSION
        
        CRITICAL FIXES (2025 Overhaul):
        1. Isolation Logic - Wait for correct business panel before extraction
        2. High-Resolution Images - Extract w1200-h800 instead of thumbnails
        3. 5-Star Review Filtering - Only extract quality reviews > 40 chars
        4. ARIA-Label Rating Extraction - Most accurate source for ratings
        5. Deep Location Attributes - Plus Code, About section, etc.
        """
        try:
            # ========================================
            # FIX 1: ISOLATION LOGIC - PREVENT DATA MISALIGNMENT
            # ========================================
            # CRITICAL: We must wait for the NEW business panel to fully load
            # before extracting ANY data. Otherwise we get stale data from previous business.
            
            # Step 1: Get expected business name from the listing BEFORE clicking
            expected_name = None
            try:
                aria_label = await element.get_attribute("aria-label")
                if aria_label:
                    expected_name = aria_label.strip()
                    logger.info(f"🎯 Clicking on: {expected_name}")
            except Exception:
                pass
            
            # Step 2: Get CURRENT h1 text (so we know when it changes)
            old_h1_text = ""
            try:
                old_h1 = await self.page.query_selector('h1.DUwDvf')
                if old_h1:
                    old_h1_text = (await old_h1.inner_text()).strip()
            except Exception:
                pass
            
            # Step 3: Click on the business to open details panel
            await element.click()
            await self._random_delay(0.5)
            
            # Step 4: WAIT for h1 to CHANGE (this is the key isolation!)
            # Poll until h1 changes OR matches expected name
            max_wait = 8  # seconds
            poll_interval = 0.3
            waited = 0
            name = "Unknown"
            
            while waited < max_wait:
                try:
                    h1_el = await self.page.query_selector('h1.DUwDvf')
                    if h1_el:
                        current_h1 = (await h1_el.inner_text()).strip()
                        
                        # Success conditions:
                        # 1. h1 changed from old value AND is not empty
                        # 2. h1 matches expected name (if we have one)
                        if current_h1 and current_h1 != old_h1_text:
                            name = current_h1
                            logger.info(f"✅ Panel loaded: {name}")
                            break
                        elif expected_name and current_h1 == expected_name:
                            name = current_h1
                            logger.info(f"✅ Panel loaded (matched expected): {name}")
                            break
                except Exception:
                    pass
                
                await asyncio.sleep(poll_interval)
                waited += poll_interval
            
            # If h1 never changed, try harder
            if name == "Unknown":
                logger.warning(f"⚠️ h1 didn't change after {max_wait}s. Trying fallbacks...")
                await self._random_delay(1.0)
                
                name_selectors = ['h1.DUwDvf', 'div.qBF1Pd.fontHeadlineSmall', 'h2.qBF1Pd']
                for name_sel in name_selectors:
                    name_el = await self.page.query_selector(name_sel)
                    if name_el:
                        name = (await name_el.inner_text()).strip()
                        if name and name != "Resultados" and len(name) > 1:
                            break
            
            # Final validation
            if name == "Unknown" or not name.strip():
                logger.error(f"❌ Failed to load panel for: {expected_name}")
                return None
            
            # Step 5: Additional wait to ensure all panel content loads
            await self._random_delay(0.8)
            
            # Extract place ID from URL
            current_url = self.page.url
            place_id = self._extract_place_id(current_url)
            
            # ========================================
            # FIX 4: ACCURATE RATINGS VIA ARIA-LABELS
            # ========================================
            # Based on actual Google Maps HTML structure:
            # Rating: <div class="F7nice"><span><span aria-hidden="true">4,6</span>...
            # Reviews: <span role="img" aria-label="228 reseñas">(228)</span>
            
            rating = 0.0
            review_count = 0
            
            # STRATEGY 1: Get rating from aria-hidden span inside F7nice div
            # This is the most reliable as it's the visible rating number
            try:
                rating_span = await self.page.query_selector('div.F7nice span[aria-hidden="true"]')
                if rating_span:
                    rating_text = await rating_span.inner_text()
                    rating = self._parse_rating(rating_text.strip())
                    logger.debug(f"Rating from aria-hidden: {rating_text} -> {rating}")
            except Exception as e:
                logger.debug(f"Rating extraction method 1 failed: {e}")
            
            # STRATEGY 2: Get review count from the span with role="img" and aria-label containing "reseñas"
            try:
                review_span = await self.page.query_selector('div.F7nice span[role="img"][aria-label*="reseña"]')
                if review_span:
                    # The aria-label has the count: "228 reseñas"
                    aria_label = await review_span.get_attribute("aria-label") or ""
                    # Extract number from "228 reseñas"
                    count_match = re.search(r'([\d\.]+)\s*reseñas?', aria_label.replace(".", ""), re.IGNORECASE)
                    if count_match:
                        review_count = int(count_match.group(1))
                        logger.debug(f"Reviews from aria-label: {aria_label} -> {review_count}")
                    else:
                        # Try getting from the visible text "(228)"
                        review_text = await review_span.inner_text()
                        review_count = self._parse_review_count(review_text)
                        logger.debug(f"Reviews from text: {review_text} -> {review_count}")
            except Exception as e:
                logger.debug(f"Review count extraction method 1 failed: {e}")
            
            # FALLBACK STRATEGY 3: Try aria-label on star rating element
            if rating == 0:
                try:
                    star_span = await self.page.query_selector('span.ceNzKf[role="img"]')
                    if star_span:
                        aria_label = await star_span.get_attribute("aria-label") or ""
                        # "4,6 estrellas"
                        rating_match = re.search(r'([\d,\.]+)\s*estrellas?', aria_label, re.IGNORECASE)
                        if rating_match:
                            rating = self._parse_rating(rating_match.group(1))
                            logger.debug(f"Rating from star aria-label: {aria_label} -> {rating}")
                except Exception as e:
                    logger.debug(f"Rating extraction method 2 failed: {e}")
            
            # FALLBACK STRATEGY 4: Traditional selectors
            if rating == 0:
                for rating_sel in ['span.MW4etd', 'div.skqShb span.MW4etd']:
                    try:
                        rating_el = await self.page.query_selector(rating_sel)
                        if rating_el:
                            rating = self._parse_rating(await rating_el.inner_text())
                            if rating > 0:
                                break
                    except:
                        pass
            
            if review_count == 0:
                for review_sel in ['span.UY7F9', 'div.skqShb span.UY7F9']:
                    try:
                        review_el = await self.page.query_selector(review_sel)
                        if review_el:
                            review_text = await review_el.inner_text()
                            review_count = self._parse_review_count(review_text)
                            if review_count > 0:
                                break
                    except:
                        pass
            
            logger.info(f"📊 {name}: ⭐{rating} ({review_count} reviews)")
            
            # Extract category
            category = None
            for cat_sel in ['button[jsaction*="category"]', 'button.DkEaL']:
                cat_el = await self.page.query_selector(cat_sel)
                if cat_el:
                    category = await cat_el.inner_text()
                    if category:
                        break
            
            # Extract address
            address = None
            addr_el = await self.page.query_selector('button[data-item-id="address"] div.Io6YTe')
            if addr_el:
                address = await addr_el.inner_text()
            if not address:
                addr_el = await self.page.query_selector('button[data-item-id="address"]')
                if addr_el:
                    address = await addr_el.inner_text()
            
            # Extract phone
            phone = None
            phone_el = await self.page.query_selector('button[data-item-id*="phone"]')
            if phone_el:
                phone = await phone_el.inner_text()
                phone = re.sub(r'[^\d+\-\s()]', '', phone)
            
            # ========================================
            # ULTRA DEEP DATA EXTRACTION
            # ========================================
            
            # 1. PRICE DATA (range, per person, voters, histogram)
            price_range = None
            price_level = 0
            price_per_person = None
            price_voters = 0
            price_histogram = {}
            
            # Basic price range from header
            for price_sel in ['span.mgr77e span', 'span.mgr77e']:
                price_el = await self.page.query_selector(price_sel)
                if price_el:
                    price_text = await price_el.inner_text()
                    price_range = self._clean_price_range(price_text)
                    price_level = self._estimate_price_level(price_range)
                    if price_range:
                        break
            
            # Price per person with voters ("₲ 20.000-40.000 por persona" + "Notificado por 79 personas")
            price_per_person_el = await self.page.query_selector('div.MNVeJb div')
            if price_per_person_el:
                ppp_text = await price_per_person_el.inner_text()
                if 'por persona' in ppp_text.lower():
                    price_per_person = self._clean_price_range(ppp_text.split('por persona')[0])
            
            voters_el = await self.page.query_selector('div.BfVpR')
            if voters_el:
                voters_text = await voters_el.inner_text()
                voters_match = re.search(r'(\d+)\s*personas?', voters_text)
                if voters_match:
                    price_voters = int(voters_match.group(1))
            
            # Price histogram
            histogram_rows = await self.page.query_selector_all('table[aria-label*="Histograma"] tr, table.rqRH4d tr')
            for row in histogram_rows:
                range_el = await row.query_selector('td.fsAi0e')
                percent_el = await row.query_selector('span.xYsBQe')
                if range_el:
                    range_text = self._clean_price_range(await range_el.inner_text())
                    percent = 0
                    if percent_el:
                        style = await percent_el.get_attribute("style") or ""
                        percent_match = re.search(r'width:\s*(\d+)%', style)
                        if percent_match:
                            percent = int(percent_match.group(1))
                    price_histogram[range_text] = percent
            
            # 2. SERVICE OPTIONS (dine_in, takeout, delivery)
            service_options = {"dine_in": False, "takeout": False, "delivery": False, "curbside_pickup": False}
            service_label_map = {
                "consumo en el lugar": "dine_in", "comer en el lugar": "dine_in",
                "comida para llevar": "takeout", "para llevar": "takeout",
                "entrega a domicilio": "delivery", "env\u00edo a domicilio": "delivery",
                "recogida en la acera": "curbside_pickup",
            }
            
            service_els = await self.page.query_selector_all('div.LTs0Rc[role="group"], div.E0DTEd div.LTs0Rc')
            for el in service_els:
                aria = await el.get_attribute("aria-label") or ""
                aria_lower = aria.lower()
                for label_text, service_key in service_label_map.items():
                    if label_text in aria_lower:
                        service_options[service_key] = "ofrece" in aria_lower
            
            # 3. ACCESSIBILITY
            accessibility = []
            access_els = await self.page.query_selector_all('span.wmQCje[aria-label]')
            for el in access_els:
                aria = await el.get_attribute("aria-label") or ""
                if "silla de ruedas" in aria.lower() or "wheelchair" in aria.lower():
                    accessibility.append("wheelchair_accessible")
            
            # 4. OPENING HOURS
            opening_hours = {}
            hours_rows = await self.page.query_selector_all('table.eK4R0e tbody tr.y0skZc')
            for row in hours_rows:
                day_el = await row.query_selector('td.ylH6lf div')
                time_el = await row.query_selector('td.mxowUb')
                if day_el and time_el:
                    day_text = await day_el.inner_text()
                    time_text = (await time_el.get_attribute("aria-label")) or (await time_el.inner_text())
                    if day_text and time_text:
                        day_key, hours_value = self._parse_hours_text(day_text, time_text)
                        opening_hours[day_key] = hours_value
            
            # Open/Closed status
            is_open_now = None
            open_status_text = None
            status_el = await self.page.query_selector('span.ZDu9vd')
            if status_el:
                open_status_text = await status_el.inner_text()
                is_open_now = "abierto" in open_status_text.lower() if open_status_text else None
            
            # 5. POPULAR TIMES (Horas Punta)
            popular_times = {}
            pop_times_container = await self.page.query_selector('div.UmE4Qe[aria-label*="punta"]')
            if pop_times_container:
                # Get all the bar charts for each day
                day_charts = await self.page.query_selector_all('div.g2BVhd')
                day_names = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday']
                
                for i, chart in enumerate(day_charts):
                    if i < len(day_names):
                        day_key = day_names[i]
                        popular_times[day_key] = {}
                        bars = await chart.query_selector_all('div.dpoVLd[role="img"]')
                        for bar in bars:
                            aria = await bar.get_attribute("aria-label") or ""
                            hour, percent = self._parse_popular_times_label(aria)
                            if hour is not None:
                                popular_times[day_key][str(hour)] = percent
            
            # 6. ORDER LINK
            order_link = None
            order_provider = None
            order_el = await self.page.query_selector('a[data-item-id="action:4"]')
            if order_el:
                order_link = await order_el.get_attribute("href")
                order_provider = self._classify_order_provider(order_link)
            
            # 7. MENU LINK
            menu_link = None
            menu_el = await self.page.query_selector('a[data-item-id="menu"], button[aria-label="Carta"]')
            if menu_el:
                menu_link = await menu_el.get_attribute("href")
            
            # 8. RESERVE LINK
            reserve_link = None
            reserve_el = await self.page.query_selector('a[data-item-id="reserve"]')
            if reserve_el:
                reserve_link = await reserve_el.get_attribute("href")
            
            # ========================================
            # FIX 5: DEEP LOCATION & ABOUT ATTRIBUTES
            # ========================================
            
            # 9. PLUS CODE (enhanced extraction)
            plus_code = None
            plus_code_selectors = [
                'button[data-item-id="oloc"] div.Io6YTe',
                'button[data-item-id="oloc"]',
                'div[data-item-id="oloc"] span',
            ]
            for plus_sel in plus_code_selectors:
                plus_el = await self.page.query_selector(plus_sel)
                if plus_el:
                    plus_text = await plus_el.inner_text()
                    # Plus codes look like "MCX9+73 Asunción" - validate format
                    if plus_text and '+' in plus_text and len(plus_text) < 50:
                        plus_code = plus_text.strip()
                        break
            
            # 10. ABOUT SECTION / BUSINESS SUMMARY
            # Google shows "From the business" or "Acerca de" with a description
            about_summary = None
            about_selectors = [
                'div[aria-label*="About"] div.WeS02d',  # English
                'div[aria-label*="Acerca"] div.WeS02d',  # Spanish  
                'div.WeS02d.fontBodyMedium',  # Generic description div
                'div.PYvSYb span',  # Alternative description location
                'div[data-attrid="kc:/local:editorial_summary"] span',
            ]
            for about_sel in about_selectors:
                about_el = await self.page.query_selector(about_sel)
                if about_el:
                    about_text = await about_el.inner_text()
                    # Only keep if it's a real description (> 20 chars, not a label)
                    if about_text and len(about_text.strip()) > 20:
                        about_summary = about_text.strip()[:500]  # Limit to 500 chars
                        break
            
            # Also try clicking "About" tab for more info
            try:
                about_tab = await self.page.query_selector('button[aria-label*="Acerca de"], button[data-tab-index="1"]')
                if about_tab and not about_summary:
                    await about_tab.click()
                    await self._random_delay(0.5)
                    
                    # Look for description in about panel
                    about_content = await self.page.query_selector('div.WeS02d, div.PYvSYb')
                    if about_content:
                        about_text = await about_content.inner_text()
                        if about_text and len(about_text.strip()) > 20:
                            about_summary = about_text.strip()[:500]
                    
                    # Go back to overview
                    overview_tab = await self.page.query_selector('button[data-tab-index="0"]')
                    if overview_tab:
                        await overview_tab.click()
                        await self._random_delay(0.3)
            except Exception as e:
                logger.debug(f"Could not extract About section: {e}")
            
            # 11. WEBSITE & SOCIAL MEDIA
            website_url = None
            website_status = "none"
            has_website = False
            social_media = {}
            
            website_el = await self.page.query_selector('a[data-item-id="authority"]')
            if website_el:
                link_url = await website_el.get_attribute("href")
                if link_url:
                    social_platform = self._classify_social_media(link_url)
                    if social_platform:
                        social_media[social_platform] = link_url
                        website_status = "social_only"
                    else:
                        website_url = link_url
                        website_status = "active"
                        has_website = True
            
            # 12. PHOTO CATEGORIES
            photo_categories = []
            photo_cat_els = await self.page.query_selector_all('div.fp2VUc button.K4UgGe')
            for el in photo_cat_els:
                label = await el.get_attribute("aria-label")
                if label and label not in ['Foto siguiente', 'Foto anterior']:
                    photo_categories.append(label)
            
            # Also get from span.zaTlhd inside photo buttons
            if not photo_categories:
                cat_labels = await self.page.query_selector_all('div.ofKBgf span.zaTlhd')
                for el in cat_labels:
                    text = await el.inner_text()
                    if text and text not in photo_categories:
                        photo_categories.append(text)
            
            # 12. REVIEW TOPICS/KEYWORDS
            review_topics = {}
            topic_els = await self.page.query_selector_all('div[role="radiogroup"] button.e2moi[aria-label]')
            for el in topic_els:
                aria = await el.get_attribute("aria-label") or ""
                if "mencionado en" in aria.lower():
                    topic, count = self._parse_review_topic(aria)
                    if topic and count > 0:
                        review_topics[topic] = count
            
            # 13. RATING DISTRIBUTION
            rating_distribution = {}
            dist_rows = await self.page.query_selector_all('tr.BHOKXe')
            for row in dist_rows:
                aria = await row.get_attribute("aria-label") or ""
                stars, count = self._parse_rating_distribution(aria)
                if stars > 0:
                    rating_distribution[str(stars)] = count
            
            # ========================================
            # FIX 3: 5-STAR REVIEW EXTRACTION (TEXT > 40 CHARS)
            # ========================================
            # CRITICAL: We need to click the reviews tab/button to load reviews
            # The main panel only shows a preview, not the full reviews list
            # 
            # HTML STRUCTURE FOR REVIEWS (from Google Maps):
            # - Each review is in: <div class="jftiEf fontBodyMedium" data-review-id="...">
            # - Reviewer name: <div class="d4r55 fontTitleMedium">
            # - Review date: <span class="rsqaWe">Hace una semana</span>
            # - Rating: <span class="kvMYJc" role="img" aria-label="5 estrellas">
            # - Review text: <div class="MyEned" lang="es"><span class="wiI7pd">text</span>
            # - Review photos: <button class="Tya61d" style="background-image: url(...)">
            # - Author info: <div class="RfnDt">Local Guide · 92 reseñas · 524 fotos</div>
            
            reviews = []
            
            # Step 1: Try to click on "Reviews" tab or "Ver todas las reseñas" button
            try:
                # Try various selectors for the reviews button/tab
                reviews_button_selectors = [
                    'button[aria-label*="reseña"]',  # "Ver todas las reseñas" button
                    'button[aria-label*="review"]',
                    'div.RWPxGd button',  # Reviews section button
                    'button[jsaction*="pane.reviewChart.moreReviews"]',
                    'a[href*="reviews"]',
                ]
                
                clicked_reviews = False
                for selector in reviews_button_selectors:
                    try:
                        review_btn = await self.page.query_selector(selector)
                        if review_btn:
                            await review_btn.click()
                            await self._random_delay(1.5)
                            clicked_reviews = True
                            logger.debug(f"Clicked reviews button with selector: {selector}")
                            break
                    except Exception:
                        continue
                
                # If we clicked, wait for review cards to appear and scroll to load more
                if clicked_reviews:
                    await self.page.wait_for_selector('div.jftiEf[data-review-id]', timeout=5000)
                    
                    # Scroll down in the reviews panel to load more reviews
                    reviews_panel = await self.page.query_selector('div.m6QErb.DxyBCb')
                    if reviews_panel:
                        for _ in range(3):  # Scroll 3 times to load more
                            await reviews_panel.evaluate('el => el.scrollTop += 500')
                            await self._random_delay(0.5)
                    
            except Exception as e:
                logger.debug(f"Could not click reviews tab: {e}")
            
            # Step 2: Now extract review cards using the correct HTML structure
            # Each review: <div class="jftiEf fontBodyMedium" aria-label="..." data-review-id="...">
            review_cards = await self.page.query_selector_all('div.jftiEf.fontBodyMedium[data-review-id]')
            
            # Fallback selector if the above doesn't work
            if len(review_cards) == 0:
                review_cards = await self.page.query_selector_all('div.jftiEf[data-review-id]')
            
            logger.debug(f"Found {len(review_cards)} review cards to process")
            
            for card in review_cards[:20]:  # Process more cards to find quality 5-star reviews
                try:
                    # First check rating - ONLY keep 5-star reviews
                    # Rating: <span class="kvMYJc" role="img" aria-label="5 estrellas">
                    rating_el = await card.query_selector('span.kvMYJc[role="img"]')
                    review_rating = 0
                    if rating_el:
                        aria = await rating_el.get_attribute("aria-label") or ""
                        stars_match = re.search(r'(\d+)\s*estrellas?', aria)
                        if stars_match:
                            review_rating = int(stars_match.group(1))
                    
                    # Skip non-5-star reviews
                    if review_rating != 5:
                        continue
                    
                    # IMPORTANT: Click "Ver más" / "Más" button to expand full review text FIRST
                    try:
                        expand_btn = await card.query_selector('button.w8nwRe.kyuRq')
                        if expand_btn:
                            await expand_btn.click()
                            await self._random_delay(0.3)
                    except Exception:
                        pass
                    
                    # Review text from: <div class="MyEned" lang="es"><span class="wiI7pd">text</span>
                    text_container = await card.query_selector('div.MyEned')
                    review_text = ""
                    if text_container:
                        text_el = await text_container.query_selector('span.wiI7pd')
                        review_text = await text_el.inner_text() if text_el else ""
                    else:
                        # Fallback: try direct span
                        text_el = await card.query_selector('span.wiI7pd')
                        review_text = await text_el.inner_text() if text_el else ""
                    
                    # FIX 3: Only keep reviews with meaningful text (> 40 chars)
                    if len(review_text.strip()) < 40:
                        continue
                    
                    # Now extract full details for this quality review
                    review_id = await card.get_attribute("data-review-id") or ""
                    
                    # Author name from: <div class="d4r55 fontTitleMedium">
                    author_el = await card.query_selector('div.d4r55.fontTitleMedium')
                    if not author_el:
                        author_el = await card.query_selector('div.d4r55')
                    author = await author_el.inner_text() if author_el else "Anónimo"
                    
                    # Author profile info: <div class="RfnDt">Local Guide · 92 reseñas · 524 fotos</div>
                    author_info_el = await card.query_selector('div.RfnDt')
                    author_info = await author_info_el.inner_text() if author_info_el else ""
                    
                    # Parse author stats
                    is_local_guide = "local guide" in author_info.lower()
                    author_reviews = 0
                    author_photos = 0
                    
                    reviews_match = re.search(r'(\d+)\s*reseñas?', author_info)
                    if reviews_match:
                        author_reviews = int(reviews_match.group(1))
                    
                    photos_match = re.search(r'(\d+)\s*fotos?', author_info)
                    if photos_match:
                        author_photos = int(photos_match.group(1))
                    
                    # Author profile URL from: <button class="al6Kxe" data-href="https://...">
                    profile_btn = await card.query_selector('button.al6Kxe[data-href]')
                    author_profile_url = ""
                    if profile_btn:
                        author_profile_url = await profile_btn.get_attribute("data-href") or ""
                    
                    # Author avatar photo: <img class="NBa7we" src="https://lh3.googleusercontent.com/...">
                    avatar_el = await card.query_selector('img.NBa7we')
                    author_avatar = ""
                    if avatar_el:
                        avatar_src = await avatar_el.get_attribute("src") or ""
                        # Upgrade avatar to higher quality (w72-h72 -> w120-h120)
                        if avatar_src:
                            author_avatar = re.sub(r'=w\d+-h\d+-', '=w120-h120-', avatar_src)
                            if author_avatar == avatar_src:  # If pattern didn't match, try old pattern
                                author_avatar = re.sub(r'=s\d+-', '=s120-', avatar_src)
                    
                    # Date from: <span class="rsqaWe">Hace una semana</span>
                    date_el = await card.query_selector('span.rsqaWe')
                    review_date = await date_el.inner_text() if date_el else ""
                    
                    # Review photos (up to 5) - UPGRADED TO HIGH-RES
                    # Photo buttons: <button class="Tya61d" style="background-image: url(&quot;https://...w600-h450-p&quot;)">
                    # We want to upgrade URLs like: w600-h450 -> w1200-h900 for high quality
                    review_photos = []
                    photo_btns = await card.query_selector_all('button.Tya61d')
                    for btn in photo_btns[:5]:
                        style = await btn.get_attribute("style") or ""
                        # Extract URL from: background-image: url("https://...w600-h450-p")
                        url_match = re.search(r'url\(["\']?([^"\'&;]+)["\']?\)', style)
                        if url_match:
                            photo_url = url_match.group(1)
                            # Clean up HTML entities if any
                            photo_url = photo_url.replace('&quot;', '').replace('&amp;', '&')
                            
                            # FIX 2: Upgrade review photos to high-res
                            # Replace w600-h450 with w1200-h900 for better quality
                            high_res_photo = re.sub(r'=w\d+-h\d+-', '=w1200-h900-', photo_url)
                            if high_res_photo == photo_url:  # If pattern didn't match
                                high_res_photo = _upgrade_to_high_res(photo_url)
                            review_photos.append(high_res_photo)
                    
                    reviews.append({
                        "review_id": review_id,
                        "author": author,
                        "author_avatar": author_avatar,
                        "author_profile_url": author_profile_url,
                        "is_local_guide": is_local_guide,
                        "author_reviews_count": author_reviews,
                        "author_photos_count": author_photos,
                        "rating": review_rating,  # Will always be 5 due to filter above
                        "date": review_date,
                        "text": review_text[:800],  # Quality text > 40 chars
                        "photos": review_photos
                    })
                    
                    # Stop after getting 10 quality 5-star reviews
                    if len(reviews) >= 10:
                        break
                        
                except Exception as e:
                    logger.debug(f"Error parsing review: {e}")
                    continue
            
            logger.info(f"💬 Extracted {len(reviews)} quality 5-star reviews with photos")
            
            # Step 3: Go back to main panel if we navigated away
            try:
                back_btn = await self.page.query_selector('button[aria-label="Atrás"], button[aria-label="Back"]')
                if back_btn:
                    await back_btn.click()
                    await self._random_delay(0.5)
            except Exception:
                pass
            
            # 15. CUSTOMER UPDATES
            customer_updates = []
            update_els = await self.page.query_selector_all('button.wjCxie')
            for el in update_els[:2]:
                try:
                    text_el = await el.query_selector('div.ZXMsO')
                    date_el = await el.query_selector('div.jrtH8d')
                    
                    update_text = await text_el.inner_text() if text_el else ""
                    update_date = await date_el.inner_text() if date_el else ""
                    
                    if update_text:
                        customer_updates.append({
                            "text": update_text[:300],
                            "date": update_date
                        })
                except Exception:
                    continue
            
            # 16. BUSINESS ATTRIBUTES FROM "INFORMACIÓN" TAB
            # These are structured attributes like Accessibility, Payments, Parking, etc.
            offerings = []
            dining_options = []
            amenities = []
            planning = []
            payments = []
            parking = []
            
            # Try to click on the "Información" tab to load these attributes
            try:
                info_tab = await self.page.query_selector('button[aria-label*="Información sobre"], button[data-tab-index="3"]')
                if info_tab:
                    await info_tab.click()
                    await self._random_delay(0.5)
                    
                    # Wait for info content to load
                    await self.page.wait_for_selector('div.iP2t7d.fontBodyMedium', timeout=3000)
                    
                    # Extract all attribute sections
                    info_sections = await self.page.query_selector_all('div.iP2t7d.fontBodyMedium')
                    
                    for section in info_sections:
                        # Get section title
                        title_el = await section.query_selector('h2.iL3Qke')
                        if not title_el:
                            continue
                        title = (await title_el.inner_text()).lower()
                        
                        # Get all items in this section
                        items = []
                        item_els = await section.query_selector_all('li.hpLkke span[aria-label]')
                        for item_el in item_els:
                            # Get the visible text (shorter version)
                            item_text = await item_el.inner_text()
                            if item_text:
                                items.append(item_text.strip())
                        
                        # Map section to appropriate field
                        if 'accesibilidad' in title:
                            accessibility.extend(items)
                        elif 'opciones de servicio' in title:
                            # Already handled by service_options, but add any extras
                            for item in items:
                                item_lower = item.lower()
                                if 'domicilio' in item_lower or 'delivery' in item_lower:
                                    service_options['delivery'] = True
                                elif 'llevar' in item_lower or 'takeout' in item_lower:
                                    service_options['takeout'] = True
                                elif 'consumo' in item_lower or 'lugar' in item_lower or 'dine' in item_lower:
                                    service_options['dine_in'] = True
                                elif 'retiro' in item_lower:
                                    service_options['curbside_pickup'] = True
                        elif 'qué ofrece' in title or 'que ofrece' in title:
                            offerings.extend(items)
                        elif 'opciones del local' in title:
                            dining_options.extend(items)
                        elif 'servicios' in title:
                            amenities.extend(items)
                        elif 'planificación' in title or 'planificacion' in title:
                            planning.extend(items)
                        elif 'pagos' in title:
                            payments.extend(items)
                        elif 'estacionamiento' in title:
                            parking.extend(items)
                    
                    # Go back to overview tab
                    overview_tab = await self.page.query_selector('button[data-tab-index="0"]')
                    if overview_tab:
                        await overview_tab.click()
                        await self._random_delay(0.3)
                        
            except Exception as e:
                logger.debug(f"Could not extract Info tab: {e}")
            
            # ========================================
            # FIX 2: HIGH-RESOLUTION IMAGE EXTRACTION (w1200-h800)
            # ========================================
            
            photo_count = 0
            photo_urls = []
            
            def _upgrade_to_high_res(url: str) -> str:
                """Convert Google image URL to high resolution (1200x800)"""
                if not url:
                    return url
                # Remove all size parameters first to avoid partial replacements
                high_res = re.sub(r'=w\d+-h\d+-[a-z]+', '=w1200-h800-k-no', url)
                high_res = re.sub(r'=w\d+-h\d+', '=w1200-h800', high_res)
                high_res = re.sub(r'=s\d+-', '=s1200-', high_res)
                # Individual size replacements for edge cases
                high_res = high_res.replace('=w80-', '=w1200-')
                high_res = high_res.replace('=w100-', '=w1200-')
                high_res = high_res.replace('=w200-', '=w1200-')
                high_res = high_res.replace('=w400-', '=w1200-')
                high_res = high_res.replace('=w800-', '=w1200-')
                high_res = high_res.replace('-h100-', '-h800-')
                high_res = high_res.replace('-h200-', '-h800-')
                high_res = high_res.replace('-h400-', '-h800-')
                high_res = high_res.replace('-h600-', '-h800-')
                return high_res
            
            # Get total photo count from button
            photos_btn = await self.page.query_selector('button[jsaction*="photos"]')
            if photos_btn:
                photos_text = await photos_btn.inner_text()
                photo_match = re.search(r'(\d+)', photos_text)
                if photo_match:
                    photo_count = int(photo_match.group(1))
            
            # Try to click on photos to get more images
            # IMPORTANT: Only extract photos from the business owner, NOT from Google recommendations
            try:
                if photos_btn and photo_count > 0:
                    await photos_btn.click()
                    await self._random_delay(1.5)
                    
                    # Wait for photo gallery to load
                    await self.page.wait_for_selector('div[data-photo-index], img.U39Pmb, div.p0Jrsd img', timeout=5000)
                    
                    # STRATEGY: Click on "Del propietario" or "By owner" tab if available
                    # This ensures we only get photos uploaded by the business owner
                    owner_tabs = [
                        'button[aria-label*="propietario"]',
                        'button[aria-label*="Del propietario"]',
                        'button[aria-label*="By owner"]',
                        'button[aria-label*="Todas"]',  # Fallback to "All" which shows main photos first
                    ]
                    for tab_selector in owner_tabs:
                        owner_tab = await self.page.query_selector(tab_selector)
                        if owner_tab:
                            try:
                                await owner_tab.click()
                                await self._random_delay(0.5)
                                logger.debug(f"Clicked on owner photos tab: {tab_selector}")
                                break
                            except:
                                pass
                    
                    # Get photos ONLY from the main gallery area, NOT from recommendations section
                    # The main gallery has specific containers, recommendations are in different divs
                    photo_selectors = [
                        # Main gallery photos (owner uploaded)
                        'div[role="tabpanel"] img[src*="googleusercontent"]',
                        'div.p0Jrsd img[src*="googleusercontent"]',
                        'img.U39Pmb[src*="googleusercontent"]',
                        'button[data-photo-index] img[src*="googleusercontent"]',
                    ]
                    
                    seen_urls = set()
                    for selector in photo_selectors:
                        img_elements = await self.page.query_selector_all(selector)
                        for img in img_elements:
                            # SKIP images inside recommendation containers
                            # Check if parent has "recommendation" or "suggestion" related classes
                            try:
                                parent_html = await img.evaluate('el => el.closest("div[class*=\'m6QErb\'], div[class*=\'recommendation\'], div[class*=\'suggest\']")?.className || ""')
                                if 'recommendation' in parent_html.lower() or 'suggest' in parent_html.lower():
                                    continue
                            except:
                                pass
                            
                            src = await img.get_attribute("src")
                            
                            if src and "googleusercontent" in src and src not in seen_urls:
                                # FIX 2: Upgrade to HIGH RESOLUTION (1200x800)
                                high_res = _upgrade_to_high_res(src)
                                seen_urls.add(high_res)
                                photo_urls.append(high_res)
                                
                                if len(photo_urls) >= 12:  # Get up to 12 owner photos
                                    break
                        if len(photo_urls) >= 12:
                            break
                    
                    # Go back to details view
                    back_btn = await self.page.query_selector('button[aria-label*="Atrás"], button[jsaction*="back"]')
                    if back_btn:
                        await back_btn.click()
                        await self._random_delay(0.5)
                    else:
                        # Press Escape to close
                        await self.page.keyboard.press("Escape")
                        await self._random_delay(0.5)
                        
            except Exception as e:
                logger.debug(f"Could not extract photo gallery: {e}")
            
            # Fallback: Get hero image (main business photo, always from owner)
            if len(photo_urls) < 3:
                # Only get the hero/main image, not sidebar recommendations
                hero_imgs = await self.page.query_selector_all('button[jsaction*="heroHeaderImage"] img')
                for img in hero_imgs[:3]:
                    src = await img.get_attribute("src")
                    if src and "googleusercontent" in src and src not in [p for p in photo_urls]:
                        high_res = _upgrade_to_high_res(src)
                        photo_urls.append(high_res)
            
            # Also get photos from reviews (these are from customers who visited, OK to include)
            review_photo_btns = await self.page.query_selector_all('div.jftiEf button.Tya61d')  # More specific: inside review cards
            for btn in review_photo_btns[:5]:
                style = await btn.get_attribute("style") or ""
                url_match = re.search(r'url\(["\']?([^"\']+googleusercontent[^"\']+)["\']?\)', style)
                if url_match:
                    src = url_match.group(1)
                    if src not in photo_urls:
                        high_res = _upgrade_to_high_res(src)
                        photo_urls.append(high_res)
            
            # Coordinates from URL
            lat, lng = None, None
            coord_match = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', current_url)
            if coord_match:
                lat = float(coord_match.group(1))
                lng = float(coord_match.group(2))
            
            # ========================================
            # BUILD BUSINESS OBJECT
            # ========================================
            
            business = ScrapedBusiness(
                name=name.strip(),
                google_place_id=place_id,
                category=category,
                address=address,
                city=location.split(",")[0].strip() if "," in location else location,
                neighborhood=location.split(",")[0].strip() if "," in location else None,
                phone=phone,
                rating=rating,
                review_count=review_count,  # FIX: Include review count
                photo_urls=photo_urls,
                photo_count=photo_count or len(photo_urls),
                has_website=has_website,
                website_url=website_url,
                website_status=website_status,
                # FIX 5: About/Description
                about_summary=about_summary,
                # Price Data
                price_range=price_range,
                price_level=price_level,
                price_per_person=price_per_person,
                price_voters=price_voters,
                price_histogram=price_histogram,
                # Services & Accessibility
                service_options=service_options,
                accessibility=accessibility,
                # Business Attributes
                offerings=offerings,
                dining_options=dining_options,
                amenities=amenities,
                planning=planning,
                payments=payments,
                parking=parking,
                # Hours & Status
                opening_hours=opening_hours,
                is_open_now=is_open_now,
                open_status_text=open_status_text,
                # Popular Times
                popular_times=popular_times,
                # Third-party Links
                order_link=order_link,
                order_provider=order_provider,
                menu_link=menu_link,
                reserve_link=reserve_link,
                # Social Media
                social_media=social_media,
                # Location
                plus_code=plus_code,
                latitude=lat,
                longitude=lng,
                # Photos
                photo_categories=photo_categories,
                # Reviews & Topics
                review_topics=review_topics,
                rating_distribution=rating_distribution,
                reviews=reviews,
                # Updates
                customer_updates=customer_updates,
            )
            
            logger.debug(f"ULTRA deep data: price_histogram={len(price_histogram)}, reviews={len(reviews)}, topics={len(review_topics)}, popular_times={len(popular_times)}")
            
            # Close panel and go back
            await self.page.keyboard.press("Escape")
            await self._random_delay(0.3)
            
            return business
            
        except Exception as e:
            logger.warning(f"Error extracting business details: {e}")
            return None
    
    async def check_website_status(self, url: str) -> str:
        """
        Check if a website URL is actually functional.
        
        Returns:
            'active', 'dead', 'social_only', or 'redirect'
        """
        if not url:
            return "none"
        
        if self._is_social_media_url(url):
            return "social_only"
        
        try:
            context = await self.browser.new_context(
                user_agent=self._get_random_user_agent()
            )
            page = await context.new_page()
            
            response = await page.goto(url, wait_until="domcontentloaded", timeout=10000)
            
            await page.close()
            await context.close()
            
            if response:
                status = response.status
                if 200 <= status < 400:
                    return "active"
                elif status >= 400:
                    return "dead"
            
            return "dead"
            
        except Exception as e:
            logger.debug(f"Website check failed for {url}: {e}")
            return "dead"
    
    async def run_discovery(
        self,
        categories: Optional[list[str]] = None,
        cities: Optional[list[str]] = None,
    ) -> list[ScrapedBusiness]:
        """
        Run full discovery process across configured locations and categories.
        
        Args:
            categories: List of category keys to search (or use config)
            cities: List of city names to search (or use config)
            
        Returns:
            All discovered businesses without websites
        """
        all_results = []
        
        # Get categories to search
        search_categories = categories or self.locations.get("search_config", {}).get(
            "categories_priority", ["restaurant", "salon"]
        )
        
        # Get cities to search
        search_cities = cities or [c["name"] for c in self.locations.get("cities", [])]
        
        try:
            await self.initialize()
            
            for city_data in self.locations.get("cities", []):
                city_name = city_data["name"]
                
                if search_cities and city_name not in search_cities:
                    continue
                
                for zone in city_data.get("zones", [{"name": city_name}]):
                    zone_name = zone.get("name", city_name)
                    location = f"{zone_name}, {city_name}"
                    
                    for category_key in search_categories:
                        cat_config = self.categories.get(category_key, {})
                        search_terms = cat_config.get("google_search_terms", [category_key])
                        
                        # Use primary search term
                        search_term = search_terms[0] if search_terms else category_key
                        
                        logger.info(f"Searching {search_term} in {location}")
                        
                        results = await self.search_businesses(
                            query=search_term,
                            location=location
                        )
                        
                        # Filter out businesses with websites
                        no_website = [b for b in results if not b.has_website]
                        all_results.extend(no_website)
                        
                        logger.info(f"Found {len(no_website)} businesses without website")
                        
                        # Respect rate limits
                        await self._random_delay(2.0)
            
        finally:
            await self.close()
        
        logger.info(f"Discovery complete. Total: {len(all_results)} businesses without websites")
        return all_results
    
    def get_results_without_website(self) -> list[ScrapedBusiness]:
        """Get only businesses that don't have a website"""
        return [b for b in self.results if not b.has_website]
    
    def export_results(self, filepath: str) -> None:
        """Export results to JSON file"""
        data = [b.to_dict() for b in self.results]
        output_path = Path(filepath)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"Exported {len(data)} results to {output_path}")


# ===========================================
# STANDALONE EXECUTION
# ===========================================

def load_existing_data(filepath: str) -> tuple[list[dict], set[str], set[str]]:
    """Load existing scraped data and extract seen names/hrefs and completed searches"""
    existing_data = []
    seen_names = set()
    seen_phones = set()
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            existing_data = json.load(f)
            for b in existing_data:
                seen_names.add(b.get('name', ''))
                if b.get('phone'):
                    seen_phones.add(b.get('phone', '').strip())
        logger.info(f"Loaded {len(existing_data)} existing businesses")
    except FileNotFoundError:
        logger.info("No existing data file found, starting fresh")
    except json.JSONDecodeError:
        logger.warning("Could not parse existing data file, starting fresh")
    
    return existing_data, seen_names, seen_phones


async def main():
    """Run discovery across multiple categories and locations - CONTINUES from existing data"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    OUTPUT_FILE = PROJECT_ROOT / "data" / "raw" / "discovered_businesses.json"
    
    # Load existing data to avoid duplicates
    existing_data, seen_names, seen_phones = load_existing_data(OUTPUT_FILE)
    logger.info(f"Starting with {len(seen_names)} known businesses to skip")
    
    scraper = MapsScraper(
        headless=False,  # Set True for production
        delay_min=2.0,
        delay_max=4.0,
        max_results_per_search=25,  # Increased to get more per search
    )
    
    # ALL POSSIBLE SEARCHES - organized by category and location
    # FOCUSED: Only Asunción (all neighborhoods) and Fernando de la Mora
    # Target: 2000 businesses total
    all_searches = [
        # === CLOTHING & FASHION ===
        ("tienda de ropa", "Villa Morra, Asunción"),
        ("tienda de ropa", "Carmelitas, Asunción"),
        ("tienda de ropa", "Centro, Asunción"),
        ("tienda de ropa", "Recoleta, Asunción"),
        ("tienda de ropa", "Sajonia, Asunción"),
        ("tienda de ropa", "Las Mercedes, Asunción"),
        ("tienda de ropa", "Fernando de la Mora, Paraguay"),
        ("boutique", "Villa Morra, Asunción"),
        ("boutique", "Carmelitas, Asunción"),
        ("boutique", "Centro, Asunción"),
        ("boutique", "Recoleta, Asunción"),
        ("boutique", "Fernando de la Mora, Paraguay"),
        ("moda mujer", "Villa Morra, Asunción"),
        ("moda mujer", "Centro, Asunción"),
        ("moda mujer", "Fernando de la Mora, Paraguay"),
        ("ropa de hombre", "Centro, Asunción"),
        ("ropa de hombre", "Villa Morra, Asunción"),
        ("ropa de niños", "Villa Morra, Asunción"),
        ("ropa de niños", "Centro, Asunción"),
        ("ropa de niños", "Fernando de la Mora, Paraguay"),
        ("ropa deportiva", "Centro, Asunción"),
        ("ropa deportiva", "Villa Morra, Asunción"),
        ("ropa deportiva", "Fernando de la Mora, Paraguay"),
        ("zapatería", "Centro, Asunción"),
        ("zapatería", "Villa Morra, Asunción"),
        ("zapatería", "Fernando de la Mora, Paraguay"),
        ("calzados", "Centro, Asunción"),
        ("calzados", "Fernando de la Mora, Paraguay"),
        ("joyería", "Centro, Asunción"),
        ("joyería", "Villa Morra, Asunción"),
        ("accesorios de moda", "Villa Morra, Asunción"),
        ("accesorios de moda", "Centro, Asunción"),
        ("lencería", "Centro, Asunción"),
        ("lencería", "Villa Morra, Asunción"),
        ("trajes", "Centro, Asunción"),
        ("vestidos", "Villa Morra, Asunción"),
        ("vestidos", "Centro, Asunción"),
        
        # === ELECTRONICS & TECHNOLOGY ===
        ("celulares", "Centro, Asunción"),
        ("celulares", "Villa Morra, Asunción"),
        ("celulares", "Fernando de la Mora, Paraguay"),
        ("electrónica", "Centro, Asunción"),
        ("electrónica", "Fernando de la Mora, Paraguay"),
        ("computadoras", "Centro, Asunción"),
        ("computadoras", "Villa Morra, Asunción"),
        ("tecnología", "Villa Morra, Asunción"),
        ("tecnología", "Centro, Asunción"),
        ("reparación de celulares", "Centro, Asunción"),
        ("reparación de celulares", "Fernando de la Mora, Paraguay"),
        
        # === FURNITURE & HOME ===
        ("mueblería", "Centro, Asunción"),
        ("mueblería", "Fernando de la Mora, Paraguay"),
        ("muebles", "Fernando de la Mora, Paraguay"),
        ("muebles", "Centro, Asunción"),
        ("decoración del hogar", "Villa Morra, Asunción"),
        ("decoración", "Centro, Asunción"),
        ("colchonería", "Centro, Asunción"),
        ("colchonería", "Fernando de la Mora, Paraguay"),
        ("electrodomésticos", "Centro, Asunción"),
        ("electrodomésticos", "Fernando de la Mora, Paraguay"),
        
        # === BEAUTY & WELLNESS ===
        ("salón de belleza", "Villa Morra, Asunción"),
        ("salón de belleza", "Carmelitas, Asunción"),
        ("salón de belleza", "Centro, Asunción"),
        ("salón de belleza", "Recoleta, Asunción"),
        ("salón de belleza", "Sajonia, Asunción"),
        ("salón de belleza", "Las Mercedes, Asunción"),
        ("salón de belleza", "Fernando de la Mora, Paraguay"),
        ("peluquería", "Centro, Asunción"),
        ("peluquería", "Villa Morra, Asunción"),
        ("peluquería", "Recoleta, Asunción"),
        ("peluquería", "Fernando de la Mora, Paraguay"),
        ("barbería", "Villa Morra, Asunción"),
        ("barbería", "Centro, Asunción"),
        ("barbería", "Recoleta, Asunción"),
        ("barbería", "Fernando de la Mora, Paraguay"),
        ("spa", "Carmelitas, Asunción"),
        ("spa", "Villa Morra, Asunción"),
        ("spa", "Recoleta, Asunción"),
        ("manicure", "Villa Morra, Asunción"),
        ("manicure", "Centro, Asunción"),
        ("uñas", "Centro, Asunción"),
        ("uñas", "Villa Morra, Asunción"),
        ("estética", "Villa Morra, Asunción"),
        ("estética", "Centro, Asunción"),
        ("estética", "Fernando de la Mora, Paraguay"),
        
        # === RESTAURANTS & FOOD ===
        ("restaurante", "Carmelitas, Asunción"),
        ("restaurante", "Villa Morra, Asunción"),
        ("restaurante", "Centro, Asunción"),
        ("restaurante", "Recoleta, Asunción"),
        ("restaurante", "Las Mercedes, Asunción"),
        ("restaurante", "Sajonia, Asunción"),
        ("restaurante", "Fernando de la Mora, Paraguay"),
        ("pizzería", "Villa Morra, Asunción"),
        ("pizzería", "Centro, Asunción"),
        ("pizzería", "Fernando de la Mora, Paraguay"),
        ("cafetería", "Carmelitas, Asunción"),
        ("cafetería", "Villa Morra, Asunción"),
        ("cafetería", "Centro, Asunción"),
        ("cafetería", "Fernando de la Mora, Paraguay"),
        ("heladería", "Carmelitas, Asunción"),
        ("heladería", "Villa Morra, Asunción"),
        ("heladería", "Centro, Asunción"),
        ("parrilla", "Villa Morra, Asunción"),
        ("parrilla", "Centro, Asunción"),
        ("parrilla", "Fernando de la Mora, Paraguay"),
        ("sushi", "Villa Morra, Asunción"),
        ("hamburguesas", "Centro, Asunción"),
        ("hamburguesas", "Villa Morra, Asunción"),
        ("hamburguesas", "Fernando de la Mora, Paraguay"),
        ("comida rápida", "Centro, Asunción"),
        ("comida rápida", "Fernando de la Mora, Paraguay"),
        ("empanadas", "Centro, Asunción"),
        ("empanadas", "Fernando de la Mora, Paraguay"),
        ("lomitería", "Centro, Asunción"),
        ("lomitería", "Fernando de la Mora, Paraguay"),
        
        # === BAKERIES & PASTRIES ===
        ("panadería", "Centro, Asunción"),
        ("panadería", "Villa Morra, Asunción"),
        ("panadería", "Recoleta, Asunción"),
        ("panadería", "Sajonia, Asunción"),
        ("panadería", "Fernando de la Mora, Paraguay"),
        ("pastelería", "Villa Morra, Asunción"),
        ("pastelería", "Centro, Asunción"),
        ("pastelería", "Fernando de la Mora, Paraguay"),
        ("confitería", "Centro, Asunción"),
        ("tortas", "Centro, Asunción"),
        ("tortas", "Villa Morra, Asunción"),
        
        # === HEALTH & MEDICAL ===
        ("dentista", "Centro, Asunción"),
        ("dentista", "Villa Morra, Asunción"),
        ("dentista", "Recoleta, Asunción"),
        ("dentista", "Las Mercedes, Asunción"),
        ("dentista", "Sajonia, Asunción"),
        ("dentista", "Fernando de la Mora, Paraguay"),
        ("clínica dental", "Centro, Asunción"),
        ("clínica dental", "Villa Morra, Asunción"),
        ("clínica dental", "Fernando de la Mora, Paraguay"),
        ("clínica médica", "Villa Morra, Asunción"),
        ("clínica médica", "Centro, Asunción"),
        ("clínica médica", "Fernando de la Mora, Paraguay"),
        ("farmacia", "Centro, Asunción"),
        ("farmacia", "Villa Morra, Asunción"),
        ("farmacia", "Fernando de la Mora, Paraguay"),
        ("óptica", "Centro, Asunción"),
        ("óptica", "Villa Morra, Asunción"),
        ("laboratorio clínico", "Centro, Asunción"),
        ("laboratorio clínico", "Fernando de la Mora, Paraguay"),
        ("fisioterapia", "Villa Morra, Asunción"),
        ("fisioterapia", "Centro, Asunción"),
        
        # === VETERINARY & PET ===
        ("veterinaria", "Villa Morra, Asunción"),
        ("veterinaria", "Recoleta, Asunción"),
        ("veterinaria", "Centro, Asunción"),
        ("veterinaria", "Sajonia, Asunción"),
        ("veterinaria", "Fernando de la Mora, Paraguay"),
        ("pet shop", "Villa Morra, Asunción"),
        ("pet shop", "Centro, Asunción"),
        ("pet shop", "Fernando de la Mora, Paraguay"),
        ("tienda de mascotas", "Centro, Asunción"),
        ("tienda de mascotas", "Fernando de la Mora, Paraguay"),
        
        # === FITNESS & SPORTS ===
        ("gimnasio", "Villa Morra, Asunción"),
        ("gimnasio", "Centro, Asunción"),
        ("gimnasio", "Recoleta, Asunción"),
        ("gimnasio", "Sajonia, Asunción"),
        ("gimnasio", "Fernando de la Mora, Paraguay"),
        ("gym", "Villa Morra, Asunción"),
        ("gym", "Fernando de la Mora, Paraguay"),
        ("crossfit", "Villa Morra, Asunción"),
        ("crossfit", "Centro, Asunción"),
        ("pilates", "Villa Morra, Asunción"),
        ("yoga", "Villa Morra, Asunción"),
        ("yoga", "Centro, Asunción"),
        ("tienda deportiva", "Centro, Asunción"),
        ("tienda deportiva", "Fernando de la Mora, Paraguay"),
        
        # === AUTOMOTIVE ===
        ("taller mecánico", "Sajonia, Asunción"),
        ("taller mecánico", "Centro, Asunción"),
        ("taller mecánico", "Fernando de la Mora, Paraguay"),
        ("gomería", "Centro, Asunción"),
        ("gomería", "Fernando de la Mora, Paraguay"),
        ("lavadero de autos", "Centro, Asunción"),
        ("lavadero de autos", "Fernando de la Mora, Paraguay"),
        ("car wash", "Villa Morra, Asunción"),
        ("repuestos de autos", "Centro, Asunción"),
        ("repuestos de autos", "Fernando de la Mora, Paraguay"),
        
        # === PROFESSIONAL SERVICES ===
        ("abogado", "Centro, Asunción"),
        ("abogado", "Villa Morra, Asunción"),
        ("contador", "Centro, Asunción"),
        ("contador", "Villa Morra, Asunción"),
        ("notaría", "Centro, Asunción"),
        ("inmobiliaria", "Villa Morra, Asunción"),
        ("inmobiliaria", "Centro, Asunción"),
        ("agencia de viajes", "Centro, Asunción"),
        ("agencia de viajes", "Villa Morra, Asunción"),
        ("seguro", "Centro, Asunción"),
        ("seguro", "Villa Morra, Asunción"),
        
        # === HOME SERVICES ===
        ("ferretería", "Centro, Asunción"),
        ("ferretería", "Sajonia, Asunción"),
        ("ferretería", "Fernando de la Mora, Paraguay"),
        ("cerrajería", "Centro, Asunción"),
        ("cerrajería", "Fernando de la Mora, Paraguay"),
        ("electricista", "Centro, Asunción"),
        ("plomero", "Centro, Asunción"),
        ("pinturería", "Centro, Asunción"),
        ("pinturería", "Fernando de la Mora, Paraguay"),
        ("vidriería", "Centro, Asunción"),
        ("vidriería", "Fernando de la Mora, Paraguay"),
        
        # === FLOWERS & GIFTS ===
        ("floristería", "Centro, Asunción"),
        ("floristería", "Villa Morra, Asunción"),
        ("flores", "Centro, Asunción"),
        ("flores", "Villa Morra, Asunción"),
        ("regalos", "Villa Morra, Asunción"),
        ("regalos", "Centro, Asunción"),
        ("librería", "Centro, Asunción"),
        ("librería", "Villa Morra, Asunción"),
        ("juguetería", "Centro, Asunción"),
        ("juguetería", "Fernando de la Mora, Paraguay"),
        
        # === MEAT & GROCERIES ===
        ("carnicería", "Centro, Asunción"),
        ("carnicería", "Fernando de la Mora, Paraguay"),
        ("supermercado", "Centro, Asunción"),
        ("supermercado", "Fernando de la Mora, Paraguay"),
        ("verdulería", "Centro, Asunción"),
        ("verdulería", "Fernando de la Mora, Paraguay"),
        ("despensa", "Centro, Asunción"),
        ("despensa", "Fernando de la Mora, Paraguay"),
        
        # === EVENTS & RENTALS ===
        ("salón de eventos", "Centro, Asunción"),
        ("salón de eventos", "Fernando de la Mora, Paraguay"),
        ("alquiler de sillas", "Centro, Asunción"),
        ("eventos", "Centro, Asunción"),
        ("eventos", "Villa Morra, Asunción"),
        ("fotografía", "Centro, Asunción"),
        ("fotografía", "Villa Morra, Asunción"),
        
        # === MOTORCYCLE ===
        ("taller de motos", "Centro, Asunción"),
        ("taller de motos", "Fernando de la Mora, Paraguay"),
        ("repuestos de motos", "Centro, Asunción"),
        
        # === EDUCATION ===
        ("academia", "Centro, Asunción"),
        ("academia", "Villa Morra, Asunción"),
        ("instituto", "Centro, Asunción"),
        ("clases particulares", "Villa Morra, Asunción"),
        ("idiomas", "Centro, Asunción"),
        ("idiomas", "Villa Morra, Asunción"),
        
        # === ADDITIONAL SERVICES ===
        ("imprenta", "Centro, Asunción"),
        ("imprenta", "Fernando de la Mora, Paraguay"),
        ("tintorería", "Villa Morra, Asunción"),
        ("tintorería", "Centro, Asunción"),
        ("lavandería", "Centro, Asunción"),
        ("lavandería", "Fernando de la Mora, Paraguay"),
        ("relojería", "Centro, Asunción"),
        ("sastrería", "Centro, Asunción"),
        ("costura", "Centro, Asunción"),
        ("costura", "Fernando de la Mora, Paraguay"),
        ("peluquería canina", "Villa Morra, Asunción"),
        ("peluquería canina", "Fernando de la Mora, Paraguay"),
        ("guardería", "Villa Morra, Asunción"),
        ("guardería", "Fernando de la Mora, Paraguay"),
        ("copias", "Centro, Asunción"),
        ("papelería", "Centro, Asunción"),
        ("papelería", "Fernando de la Mora, Paraguay"),
        ("kiosco", "Centro, Asunción"),
        ("minimarket", "Centro, Asunción"),
        ("minimarket", "Fernando de la Mora, Paraguay"),
    ]
    
    # Track all results (including updates to existing)
    all_results = []
    all_results_dict = {}  # name -> business dict for deduplication
    searches_completed = 0
    
    # OPTION: Set to True to RE-SCRAPE all businesses (update existing data)
    RESCRAPE_ALL = True  # Change to False to skip existing businesses
    
    try:
        await scraper.initialize()
        
        for query, location in all_searches:
            logger.info(f"\n{'='*50}")
            logger.info(f"Searching: {query} in {location}")
            logger.info(f"{'='*50}")
            
            try:
                results = await scraper.search_businesses(
                    query=query,
                    location=location,
                    max_results=20  # Get 20 results per search
                )
                
                # Add/update businesses
                added_count = 0
                updated_count = 0
                for r in results:
                    r_dict = r.to_dict()
                    
                    if RESCRAPE_ALL:
                        # Always add/update - overwrite existing with new data
                        if r.name in all_results_dict:
                            all_results_dict[r.name] = r_dict
                            updated_count += 1
                        else:
                            all_results_dict[r.name] = r_dict
                            added_count += 1
                    else:
                        # Only add truly new businesses (old behavior)
                        phone_clean = (r.phone or '').strip()
                        is_duplicate = (
                            r.name in seen_names or 
                            (phone_clean and phone_clean in seen_phones)
                        )
                        
                        if not is_duplicate:
                            seen_names.add(r.name)
                            if phone_clean:
                                seen_phones.add(phone_clean)
                            all_results_dict[r.name] = r_dict
                            added_count += 1
                
                if RESCRAPE_ALL:
                    logger.info(f"Scraped {len(results)} businesses ({added_count} new, {updated_count} updated)")
                else:
                    logger.info(f"Added {added_count} NEW businesses (skipped {len(results) - added_count} duplicates)")
                
                searches_completed += 1
                
                # Save progress every 5 searches
                if searches_completed % 5 == 0:
                    all_results = list(all_results_dict.values())
                    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
                    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                        json.dump(all_results, f, ensure_ascii=False, indent=2)
                    logger.info(f"💾 Progress saved: {len(all_results)} total businesses")
                
            except Exception as e:
                logger.error(f"Error searching {query} in {location}: {e}")
                continue
            
            # Delay between searches
            await asyncio.sleep(random.uniform(3, 5))
        
        # Final save
        all_results = list(all_results_dict.values())
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)
        
        # Summary
        no_website = [b for b in all_results if not b.get('has_website', True)]
        
        print(f"\n{'='*60}")
        print(f"DISCOVERY COMPLETE")
        print(f"{'='*60}")
        if RESCRAPE_ALL:
            print(f"RE-SCRAPE MODE: All businesses updated with new data")
        else:
            print(f"Previous businesses: {len(existing_data)}")
        print(f"Total businesses scraped: {len(all_results)}")
        print(f"Businesses without website: {len(no_website)}")
        print(f"{'='*60}\n")
        
    finally:
        await scraper.close()


if __name__ == "__main__":
    asyncio.run(main())

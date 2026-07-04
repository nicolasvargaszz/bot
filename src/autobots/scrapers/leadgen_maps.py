"""
Lead-gen Google Maps scraper — card-only, high-message-volume niches.

Unlike ``google_maps.MapsScraper`` (deep per-business extraction, clicks into
every result), this module parses the search-results feed cards only. It never
navigates to ``/maps/place/…`` paths: the single entry point is
``https://www.google.com/maps?hl=es`` (explicitly allowed by Google's
robots.txt via ``Allow: /maps?hl=``), and everything else happens inside the
already-loaded page. One search yields 20–30 leads in ~90 seconds.

Target profile: businesses that receive high WhatsApp message volume and can
buy an n8n automation — clinics, hospitals, pharmacies, labs, retail
(electronics, furniture, hardware), insurers. Generic food places are
deliberately excluded.

Layers (kept separate on purpose):
    collect_raw_cards()  fetch  — browser only, returns raw dicts
    parse_card()         parse  — pure function, unit-tested
    append_leads()       store  — JSONL append, resume-friendly
    scrape()             orchestrator — rate limiting, retries, summary
"""

import asyncio
import json
import logging
import os
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from autobots.scrapers.google_maps import MapsScraper, SELECTORS
from autobots.utils.phone import is_valid_paraguay_phone, normalize_paraguay_phone_digits

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_PATH = PROJECT_ROOT / "data" / "raw" / "leadgen_maps.jsonl"
FAILED_PATH = PROJECT_ROOT / "data" / "raw" / "leadgen_failed.txt"

# Minimum seconds between searches; card scrolling reuses MapsScraper delays.
SEARCH_DELAY = 4.0
MAX_RETRIES_PER_SEARCH = 2

# (query, location, niche_key) — high message volume, sellable n8n automation.
# No generic food businesses.
SEARCHES: list[tuple[str, str, str]] = [
    ("clínica médica", "Asunción", "clinica"),
    ("clínica odontológica", "Asunción", "odontologia"),
    ("sanatorio", "Asunción", "sanatorio"),
    ("hospital privado", "Asunción", "hospital"),
    ("centro médico", "Luque", "clinica"),
    ("laboratorio de análisis clínicos", "Asunción", "laboratorio"),
    ("farmacia", "Villa Morra, Asunción", "farmacia"),
    ("farmacia", "San Lorenzo", "farmacia"),
    ("óptica", "Asunción", "optica"),
    ("clínica veterinaria", "Asunción", "veterinaria"),
    ("tienda de electrónica", "Asunción", "electronica"),
    ("casa de electrodomésticos", "Asunción", "electrodomesticos"),
    ("mueblería", "Fernando de la Mora", "muebleria"),
    ("ferretería industrial", "Asunción", "ferreteria"),
    ("aseguradora", "Asunción", "aseguradora"),
]

# Relative weight of each niche for the automation-fit score: how much WhatsApp
# volume the niche handles and how repetitive/automatable those questions are.
NICHE_WEIGHTS = {
    "hospital": 30,
    "sanatorio": 30,
    "clinica": 26,
    "farmacia": 26,
    "aseguradora": 25,
    "odontologia": 22,
    "laboratorio": 20,
    "electronica": 20,
    "electrodomesticos": 20,
    "ferreteria": 18,
    "veterinaria": 16,
    "optica": 15,
    "muebleria": 15,
}


# ===========================================
# PARSE — pure functions (unit-tested)
# ===========================================

def _parse_reviews_count(text: str) -> int:
    """'(1.234)' / '(206)' / '206 reseñas' -> int."""
    if not text:
        return 0
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0


def _parse_rating(text: str) -> float:
    """'4,6' / '4.6' -> float."""
    if not text:
        return 0.0
    match = re.search(r"\d+[.,]?\d*", text)
    return float(match.group(0).replace(",", ".")) if match else 0.0


def _extract_category(info_lines: list[str]) -> Optional[str]:
    """First segment before '·' in the first info line that has one."""
    for line in info_lines:
        if "·" in line:
            candidate = line.split("·")[0].strip()
            # Skip status lines ("Abierto", "Cerrado", hours)
            if candidate and not re.match(r"^(abierto|cerrado|abre|cierra)", candidate, re.I):
                return candidate
    return None


def parse_card(raw: dict, query: str, location: str, niche: str) -> Optional[dict]:
    """Turn a raw card dict from the fetch layer into a validated lead record.

    Returns None when the record fails validation (no name, or neither a
    phone nor an address to act on).
    """
    name = (raw.get("aria_name") or "").strip()
    if not name:
        return None

    phone_digits = normalize_paraguay_phone_digits(raw.get("phone_text"))
    has_phone = bool(phone_digits and is_valid_paraguay_phone(raw.get("phone_text")))

    info_lines = [line for line in (raw.get("info_lines") or []) if line]
    category = _extract_category(info_lines)

    if not has_phone and not info_lines:
        return None

    # Mobile numbers (09xx -> 5959xx) can receive WhatsApp directly.
    is_mobile = bool(phone_digits and phone_digits.startswith("5959"))

    return {
        "name": name,
        "niche": niche,
        "category": category,
        "query": query,
        "location": location,
        "rating": _parse_rating(raw.get("rating_text") or ""),
        "review_count": _parse_reviews_count(raw.get("reviews_text") or ""),
        "phone": phone_digits if has_phone else None,
        "phone_is_mobile": is_mobile,
        "has_website": bool(raw.get("has_website_link")),
        "info_lines": info_lines[:3],
        "place_href": raw.get("href") or None,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }


def score_lead(lead: dict) -> int:
    """0–100 automation-fit score: message volume proxy + reachability."""
    score = NICHE_WEIGHTS.get(lead.get("niche", ""), 12)

    reviews = lead.get("review_count") or 0
    if reviews >= 500:
        score += 30
    elif reviews >= 200:
        score += 25
    elif reviews >= 100:
        score += 20
    elif reviews >= 50:
        score += 15
    elif reviews >= 20:
        score += 10
    elif reviews >= 5:
        score += 5

    if lead.get("phone"):
        score += 15 if lead.get("phone_is_mobile") else 8

    rating = lead.get("rating") or 0
    if 3.8 <= rating <= 4.9:
        score += 5

    # No website: they already run the business on WhatsApp/social — an easy
    # automation sale plus a landing-page upsell.
    if not lead.get("has_website"):
        score += 10

    return min(score, 100)


def dedup_key(lead: dict) -> str:
    """Same business found by two searches collapses to one record."""
    return lead.get("phone") or (lead.get("place_href") or lead["name"]).split("?")[0]


# ===========================================
# STORE — JSONL, resume-friendly
# ===========================================

def load_seen(path: Path = OUTPUT_PATH) -> set[str]:
    seen: set[str] = set()
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    seen.add(dedup_key(json.loads(line)))
                except (json.JSONDecodeError, KeyError):
                    continue
    return seen


def append_leads(leads: list[dict], path: Path = OUTPUT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for lead in leads:
            f.write(json.dumps(lead, ensure_ascii=False) + "\n")


def log_failed(search: str, reason: str, path: Path = FAILED_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()}\t{search}\t{reason}\n")


# ===========================================
# FETCH — browser only
# ===========================================

async def collect_raw_cards(scraper: MapsScraper, query: str, location: str,
                            max_results: int) -> list[dict]:
    """Search Google Maps and harvest raw card data from the results feed.

    Stays on the search-results page; never opens individual place panels.
    """
    page = scraper.page
    search_query = f"{query} en {location}, Paraguay"

    await page.goto("https://www.google.com/maps?hl=es", wait_until="domcontentloaded")
    await scraper._random_delay(0.6)

    # Cookie consent (same handling as MapsScraper.search_businesses)
    for selector in ('button[aria-label*="Aceptar"]', 'button[aria-label*="Accept"]',
                     "button#L2AGLb"):
        try:
            btn = await page.query_selector(selector)
            if btn:
                await btn.click()
                await scraper._random_delay(0.4)
                break
        except Exception:
            continue

    search_box = await page.wait_for_selector(SELECTORS["search_input"], timeout=10000)
    await search_box.click()
    await search_box.fill(search_query)
    await page.keyboard.press("Enter")
    await scraper._random_delay(1.2)

    await page.wait_for_selector('div[role="feed"]', timeout=15000)

    # Scroll the feed until we have enough cards or it stops growing.
    seen_hrefs: set[str] = set()
    raw_cards: list[dict] = []
    stagnant = 0
    while len(raw_cards) < max_results and stagnant < 6:
        cards = await page.query_selector_all("div.Nv2PK")
        new_in_pass = 0
        for card in cards:
            link = await card.query_selector("a.hfpxzc")
            if not link:
                continue
            href = await link.get_attribute("href") or ""
            if not href or href in seen_hrefs:
                continue
            seen_hrefs.add(href)
            new_in_pass += 1

            rating_el = await card.query_selector("span.MW4etd")
            reviews_el = await card.query_selector("span.UY7F9")
            phone_el = await card.query_selector("span.UsdlK")
            website_el = await card.query_selector('a[data-value="Sitio web"]')
            info_els = await card.query_selector_all("div.W4Efsd")

            info_lines = []
            for el in info_els:
                text = (await el.inner_text()).replace("\n", " · ").strip()
                if text and text not in info_lines:
                    info_lines.append(text)

            raw_cards.append({
                "aria_name": await link.get_attribute("aria-label"),
                "href": href,
                "rating_text": await rating_el.inner_text() if rating_el else "",
                "reviews_text": await reviews_el.inner_text() if reviews_el else "",
                "phone_text": await phone_el.inner_text() if phone_el else "",
                "has_website_link": website_el is not None,
                "info_lines": info_lines,
            })

        stagnant = stagnant + 1 if new_in_pass == 0 else 0
        feed = await page.query_selector('div[role="feed"]')
        if feed:
            await feed.evaluate("el => el.scrollBy(0, 1200)")
        await scraper._random_delay(0.5)

        end_marker = await page.query_selector("span.HlvSq")
        if end_marker:
            break

    return raw_cards[:max_results]


# ===========================================
# ORCHESTRATOR
# ===========================================

async def scrape(searches: list[tuple[str, str, str]] = SEARCHES,
                 max_results_per_search: int = 25,
                 output_path: Path = OUTPUT_PATH) -> dict:
    """Run every search with rate limiting and retries; append leads to JSONL.

    Resume-safe: businesses already present in the output file are skipped.
    """
    stats = {"fetched": 0, "parsed": 0, "failed": 0, "skipped": 0}
    seen = load_seen(output_path)
    logger.info("Resume: %d leads already stored", len(seen))

    scraper = MapsScraper(
        headless=os.environ.get("HEADLESS_BROWSER", "true").lower() != "false",
        delay_min=2.0,
        delay_max=4.0,
    )
    await scraper.initialize()

    try:
        for query, location, niche in searches:
            label = f"{query} | {location}"
            raw_cards: list[dict] = []

            for attempt in range(1, MAX_RETRIES_PER_SEARCH + 2):
                try:
                    raw_cards = await collect_raw_cards(
                        scraper, query, location, max_results_per_search
                    )
                    break
                except Exception as exc:  # noqa: BLE001 — one search must not kill the run
                    if attempt > MAX_RETRIES_PER_SEARCH:
                        logger.error("FAILED %s: %s", label, exc)
                        log_failed(label, str(exc))
                        stats["failed"] += 1
                    else:
                        backoff = 5 * attempt
                        logger.warning("Retry %d for %s in %ds (%s)", attempt, label, backoff, exc)
                        await asyncio.sleep(backoff)

            stats["fetched"] += len(raw_cards)
            fresh: list[dict] = []
            for raw in raw_cards:
                lead = parse_card(raw, query, location, niche)
                if lead is None:
                    continue
                key = dedup_key(lead)
                if key in seen:
                    stats["skipped"] += 1
                    continue
                seen.add(key)
                lead["score"] = score_lead(lead)
                fresh.append(lead)

            append_leads(fresh, output_path)
            stats["parsed"] += len(fresh)
            logger.info("%s -> %d cards, %d new leads (total %d)",
                        label, len(raw_cards), len(fresh), stats["parsed"])

            await asyncio.sleep(SEARCH_DELAY + random.uniform(0, 2))
    finally:
        await scraper.close()

    logger.info("SUMMARY: %(fetched)d fetched, %(parsed)d parsed, "
                "%(failed)d failed, %(skipped)d skipped", stats)
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(scrape())

"""Scraper de agentes inmobiliarios de Properstar.

Flujo:
1. Recorre las paginas de agentes y extrae las URLs de perfil.
2. Visita cada perfil y captura datos comerciales/contacto en CSV.

El scraper usa Playwright porque Properstar puede cargar parte del contenido
con JavaScript y porque algunas secciones aparecen despues de hacer scroll.
"""

from __future__ import annotations

import asyncio
import csv
import logging
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from playwright.async_api import (
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Locator,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)


logger = logging.getLogger(__name__)

BASE_DOMAIN = "https://www.properstar.es"
DEFAULT_START_URL = (
    "https://www.properstar.es/paraguay/asuncion-l2/agentes-inmobiliarios"
)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

CSV_FIELDS = [
    "url_perfil",
    "nombre_agente",
    "sobre_mi",
    "precio_venta_medio",
    "anuncios_para_la_venta",
    "idiomas_hablados",
    "nombre_agencia",
    "telefono_contacto",
    "direccion_fisica",
    "ciudad_codigo_postal",
    "url_sitio_web_agencia",
]


@dataclass
class AgentSeed:
    """Datos preliminares extraidos desde la tarjeta del listado."""

    profile_url: str
    name: Optional[str] = None
    agency: Optional[str] = None
    bio: Optional[str] = None
    listings_for_sale: Optional[str] = None
    languages: Optional[str] = None


@dataclass
class AgentProfile:
    """Datos finales de un agente."""

    profile_url: str
    name: Optional[str] = None
    bio: Optional[str] = None
    average_sale_price: Optional[str] = None
    listings_for_sale: Optional[str] = None
    languages: Optional[str] = None
    agency: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city_postal_code: Optional[str] = None
    agency_website: Optional[str] = None

    def to_csv_row(self) -> Dict[str, str]:
        """Convierte None a cadenas vacias para un CSV limpio."""

        return {
            "url_perfil": self.profile_url,
            "nombre_agente": self.name or "",
            "sobre_mi": self.bio or "",
            "precio_venta_medio": self.average_sale_price or "",
            "anuncios_para_la_venta": self.listings_for_sale or "",
            "idiomas_hablados": self.languages or "",
            "nombre_agencia": self.agency or "",
            "telefono_contacto": self.phone or "",
            "direccion_fisica": self.address or "",
            "ciudad_codigo_postal": self.city_postal_code or "",
            "url_sitio_web_agencia": self.agency_website or "",
        }


def clean_text(value: Optional[str]) -> Optional[str]:
    """Normaliza espacios sin destruir acentos ni signos utiles."""

    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned or None


def build_listing_page_url(start_url: str, page_number: int) -> str:
    """Properstar pagina con ?p=N; la primera se puede pedir sin parametro."""

    if page_number <= 1:
        return start_url

    parts = urlsplit(start_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["p"] = str(page_number)
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def normalize_profile_url(href: Optional[str]) -> Optional[str]:
    if not href:
        return None
    return urljoin(BASE_DOMAIN, href)


def normalize_website_url(raw_value: Optional[str]) -> Optional[str]:
    """Limpia hrefs normales y tambien formatos raros tipo markdown."""

    value = clean_text(raw_value)
    if not value:
        return None

    url_match = re.search(r"https?://[^\]\)\s]+", value)
    if url_match:
        return url_match.group(0)

    if value.startswith("//"):
        return f"https:{value}"

    if value.startswith(("mailto:", "tel:")):
        return None

    if "." in value and " " not in value and not urlsplit(value).scheme:
        return f"https://{value.strip('/')}"

    return value


async def random_wait(min_delay: float, max_delay: float) -> None:
    await asyncio.sleep(random.uniform(min_delay, max_delay))


async def goto_with_retries(
    page: Page,
    url: str,
    timeout_ms: int,
    retries: int = 2,
) -> bool:
    """Navega con reintentos cortos para tolerar timeouts esporadicos."""

    for attempt in range(1, retries + 2):
        try:
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )
            try:
                await page.wait_for_load_state("networkidle", timeout=10_000)
            except PlaywrightTimeoutError:
                # El sitio puede mantener conexiones abiertas; no es fatal.
                pass

            status = response.status if response else None
            if status and status >= 400:
                logger.warning("HTTP %s al abrir %s", status, url)
            return True
        except (PlaywrightTimeoutError, PlaywrightError) as exc:
            logger.warning(
                "Intento %s/%s fallido para %s: %s",
                attempt,
                retries + 1,
                url,
                exc,
            )
            await asyncio.sleep(1.5 * attempt)

    return False


async def accept_cookie_banner(page: Page) -> None:
    """Cierra banners comunes de cookies si aparecen."""

    selectors = [
        'button:has-text("Aceptar")',
        'button:has-text("Acepto")',
        'button:has-text("Aceptar todo")',
        'button:has-text("Accept")',
        'button[id*="accept" i]',
        '[data-testid*="accept" i]',
    ]

    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if await locator.count():
                await locator.click(timeout=1_500)
                await page.wait_for_timeout(500)
                return
        except PlaywrightError:
            continue


async def auto_scroll(page: Page, steps: int = 5) -> None:
    """Hace scroll para disparar contenido lazy sin ser agresivo."""

    for _ in range(steps):
        await page.mouse.wheel(0, random.randint(450, 900))
        await page.wait_for_timeout(random.randint(250, 650))


async def first_text(
    scope: Page | Locator,
    selectors: Sequence[str],
    max_matches_per_selector: int = 4,
) -> Optional[str]:
    """Devuelve el primer texto no vacio que matchee alguno de los selectores."""

    for selector in selectors:
        locator = scope.locator(selector)
        try:
            count = min(await locator.count(), max_matches_per_selector)
        except PlaywrightError:
            continue

        for index in range(count):
            try:
                text = clean_text(await locator.nth(index).inner_text(timeout=1_500))
            except PlaywrightError:
                continue
            if text:
                return text

    return None


async def first_attribute(
    scope: Page | Locator,
    selectors: Sequence[str],
    attribute: str,
    max_matches_per_selector: int = 4,
) -> Optional[str]:
    """Devuelve el primer atributo no vacio que matchee alguno de los selectores."""

    for selector in selectors:
        locator = scope.locator(selector)
        try:
            count = min(await locator.count(), max_matches_per_selector)
        except PlaywrightError:
            continue

        for index in range(count):
            try:
                value = clean_text(
                    await locator.nth(index).get_attribute(attribute, timeout=1_500)
                )
            except PlaywrightError:
                continue
            if value:
                return value

    return None


async def feature_value_from_scope(
    scope: Page | Locator,
    label_candidates: Iterable[str],
) -> Optional[str]:
    """Busca pares label/value como los de las tarjetas y perfiles de Properstar."""

    labels = list(label_candidates)
    script = """
        (root, labels) => {
            const normalize = (text) => (text || "")
                .normalize("NFD")
                .replace(/[\\u0300-\\u036f]/g, "")
                .replace(/\\s+/g, " ")
                .trim()
                .toLowerCase();

            const wanted = labels.map(normalize);
            const matches = (text) => {
                const normalized = normalize(text);
                return wanted.some((label) => normalized.includes(label));
            };

            const containers = Array.from(root.querySelectorAll(
                ".feature, [class*='feature'], [class*='stat'], dl, li"
            ));

            for (const container of containers) {
                const labelElement = container.querySelector(
                    ".label, [class*='label'], dt, [class*='title']"
                );
                const valueElement = container.querySelector(
                    ".value, [class*='value'], dd, strong, b"
                );

                const label = labelElement?.innerText || "";
                if (!label || !matches(label)) {
                    continue;
                }

                const value = (
                    valueElement?.innerText ||
                    container.innerText.replace(label, "")
                )
                    .replace(/\\s+/g, " ")
                    .trim();

                if (value) {
                    return value;
                }
            }

            const leaves = Array.from(root.querySelectorAll("*"))
                .filter((element) => element.children.length === 0);

            for (const labelElement of leaves) {
                if (!matches(labelElement.innerText)) {
                    continue;
                }

                const parent = labelElement.parentElement;
                if (!parent) {
                    continue;
                }

                const siblings = Array.from(parent.children);
                const siblingValue = siblings
                    .map((element) => element.innerText)
                    .find((text) => text && !matches(text));

                if (siblingValue) {
                    return siblingValue.replace(/\\s+/g, " ").trim();
                }
            }

            return null;
        }
    """

    try:
        if isinstance(scope, Page):
            value = await scope.evaluate(
                f"(labels) => ({script})(document, labels)",
                labels,
            )
        else:
            value = await scope.evaluate(script, labels)
    except PlaywrightError:
        return None

    return clean_text(value)


async def section_text_by_heading(
    page: Page,
    heading_candidates: Iterable[str],
) -> Optional[str]:
    """Extrae texto de una seccion cuando el titulo visible es conocido."""

    headings = list(heading_candidates)
    try:
        value = await page.evaluate(
            """
            (headings) => {
                const normalize = (text) => (text || "")
                    .normalize("NFD")
                    .replace(/[\\u0300-\\u036f]/g, "")
                    .replace(/\\s+/g, " ")
                    .trim()
                    .toLowerCase();

                const wanted = headings.map(normalize);
                const matches = (text) => {
                    const normalized = normalize(text);
                    return wanted.some((heading) => normalized === heading);
                };

                const titleElements = Array.from(document.querySelectorAll(
                    "h1, h2, h3, h4, [class*='heading'], [class*='title']"
                ));

                for (const titleElement of titleElements) {
                    if (!matches(titleElement.innerText)) {
                        continue;
                    }

                    const section = titleElement.closest("section, article, div");
                    if (!section) {
                        continue;
                    }

                    const pieces = Array.from(section.querySelectorAll(
                        "p, small, [class*='description'], [class*='bio'], [class*='about']"
                    ))
                        .map((element) => element.innerText)
                        .map((text) => (text || "").replace(/\\s+/g, " ").trim())
                        .filter((text) => text && !matches(text));

                    const joined = pieces.join(" ").trim();
                    if (joined) {
                        return joined;
                    }
                }

                return null;
            }
            """,
            headings,
        )
    except PlaywrightError:
        return None

    return clean_text(value)


async def reveal_contact_info(page: Page) -> None:
    """Intenta revelar telefono/contacto si el sitio lo oculta tras un boton."""

    selectors = [
        'button:has-text("Mostrar teléfono")',
        'button:has-text("Ver teléfono")',
        'button:has-text("Teléfono")',
        'button:has-text("telefono")',
        '.phone-block button',
        '.agency-contact-info button',
    ]

    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if not await locator.count():
                continue
            await locator.click(timeout=2_000)
            await page.wait_for_timeout(random.randint(500, 1_200))
        except PlaywrightError:
            continue


async def extract_seed_from_card(card: Locator) -> Optional[AgentSeed]:
    href = await first_attribute(
        card,
        [
            'a.link.stretched-link[href*="/agente-de-bienes-raices/"]',
            'a[href*="/agente-de-bienes-raices/"]',
        ],
        "href",
    )
    profile_url = normalize_profile_url(href)
    if not profile_url:
        return None

    return AgentSeed(
        profile_url=profile_url,
        name=await first_text(card, ["h3.heading.name", ".heading.name", ".name", "h3"]),
        agency=await first_text(card, [".agency"]),
        bio=await first_text(card, ["small.item-bio", ".item-bio", "[class*='bio']"]),
        listings_for_sale=await feature_value_from_scope(
            card,
            ["Anuncios para la venta"],
        ),
        languages=await feature_value_from_scope(card, ["Idiomas hablados", "Idiomas"]),
    )


async def extract_agent_links_from_listing_page(page: Page) -> List[AgentSeed]:
    """Extrae los perfiles desde una pagina de listado."""

    try:
        await page.wait_for_selector(
            '.place-agents-list article.item, a[href*="/agente-de-bienes-raices/"]',
            timeout=15_000,
        )
    except PlaywrightTimeoutError:
        return []

    await auto_scroll(page, steps=3)

    cards = page.locator(".place-agents-list article.item, article.item")
    seeds: List[AgentSeed] = []
    seen_urls = set()

    for index in range(await cards.count()):
        seed = await extract_seed_from_card(cards.nth(index))
        if not seed or seed.profile_url in seen_urls:
            continue
        seeds.append(seed)
        seen_urls.add(seed.profile_url)

    if seeds:
        return seeds

    # Fallback por si cambia la estructura de article.item.
    links = page.locator('a[href*="/agente-de-bienes-raices/"]')
    for index in range(await links.count()):
        href = await links.nth(index).get_attribute("href")
        profile_url = normalize_profile_url(href)
        if not profile_url or profile_url in seen_urls:
            continue
        seeds.append(AgentSeed(profile_url=profile_url))
        seen_urls.add(profile_url)

    return seeds


async def collect_agent_seeds(
    context: BrowserContext,
    start_url: str,
    max_pages: Optional[int],
    max_agents: Optional[int],
    min_delay: float,
    max_delay: float,
    timeout_ms: int,
) -> List[AgentSeed]:
    """Recorre la paginacion y acumula URLs unicas de perfiles."""

    page = await context.new_page()
    seed_by_url: Dict[str, AgentSeed] = {}
    page_number = 1

    try:
        while True:
            if max_pages is not None and page_number > max_pages:
                break

            listing_url = build_listing_page_url(start_url, page_number)
            logger.info("Listado pagina %s: %s", page_number, listing_url)

            if not await goto_with_retries(page, listing_url, timeout_ms):
                logger.warning("No se pudo abrir el listado %s", listing_url)
                break

            await accept_cookie_banner(page)
            page_seeds = await extract_agent_links_from_listing_page(page)
            new_count = 0

            for seed in page_seeds:
                if seed.profile_url in seed_by_url:
                    continue
                seed_by_url[seed.profile_url] = seed
                new_count += 1
                if max_agents is not None and len(seed_by_url) >= max_agents:
                    break

            logger.info(
                "Pagina %s: %s perfiles detectados, %s nuevos, %s acumulados",
                page_number,
                len(page_seeds),
                new_count,
                len(seed_by_url),
            )

            if max_agents is not None and len(seed_by_url) >= max_agents:
                break

            if not page_seeds or new_count == 0:
                logger.info("Fin de paginacion detectado en pagina %s", page_number)
                break

            page_number += 1
            await random_wait(min_delay, max_delay)
    finally:
        await page.close()

    return list(seed_by_url.values())


async def scrape_agent_profile(
    context: BrowserContext,
    seed: AgentSeed,
    min_delay: float,
    max_delay: float,
    timeout_ms: int,
) -> AgentProfile:
    """Extrae los datos requeridos desde el perfil individual."""

    page = await context.new_page()
    try:
        if not await goto_with_retries(page, seed.profile_url, timeout_ms):
            return AgentProfile(
                profile_url=seed.profile_url,
                name=seed.name,
                bio=seed.bio,
                listings_for_sale=seed.listings_for_sale,
                languages=seed.languages,
                agency=seed.agency,
            )

        await accept_cookie_banner(page)
        await auto_scroll(page, steps=6)
        await reveal_contact_info(page)

        title_name = clean_text(await page.title())
        if title_name:
            title_name = re.split(r"\s[-|]\sProperstar", title_name, maxsplit=1)[0]

        name = (
            await first_text(
                page,
                [
                    "h1.heading.name",
                    ".agent-name h1",
                    "[class*='agent'] h1",
                    "h1",
                ],
            )
            or seed.name
            or title_name
        )

        bio = (
            await first_text(
                page,
                [
                    ".agent-description",
                    ".agent-bio",
                    ".profile-bio",
                    ".profile-description",
                    "[class*='biography']",
                    "[class*='about'] p",
                ],
            )
            or await section_text_by_heading(page, ["Sobre mí", "Sobre mi", "Biografía"])
            or seed.bio
        )

        average_sale_price = await feature_value_from_scope(
            page,
            [
                "Precio de venta medio",
                "Precio medio de venta",
                "Precio promedio de venta",
            ],
        )

        listings_for_sale = (
            await feature_value_from_scope(
                page,
                ["Anuncios para la venta", "Propiedades en venta"],
            )
            or seed.listings_for_sale
        )
        languages = (
            await feature_value_from_scope(page, ["Idiomas hablados", "Idiomas"])
            or seed.languages
        )

        agency = (
            await first_text(
                page,
                [
                    ".agency-card .agency-name",
                    ".agency-contact .agency-name",
                    ".agency-profile .agency-name",
                    ".profile-agency .agency-name",
                    ".agent-agency .agency-name",
                    ".agency-name",
                    ".agent-agency",
                    ".profile-agency",
                    ".agency",
                ],
            )
            or seed.agency
        )

        phone = await first_text(
            page,
            [
                ".agency-contact-info .agency-phone.phone-number",
                ".agency-contact-info .phone-number",
                ".phone-block .agency-phone",
                ".phone-block .phone-number",
                "a[href^='tel:']",
            ],
        )
        if not phone:
            phone_href = await first_attribute(page, ["a[href^='tel:']"], "href")
            phone = clean_text(phone_href.replace("tel:", "")) if phone_href else None

        address = await first_text(
            page,
            [
                ".agency-contact-info .address-block .address",
                ".agency-contact-info .address",
                ".address-block .address",
                ".address-block",
            ],
        )

        city_postal_code = await first_text(
            page,
            [
                ".agency-contact-info .city-block",
                ".city-block",
                "[class*='postal']",
            ],
        )

        website_href = await first_attribute(
            page,
            [
                ".agency-contact-info .websiteurl-block a.website",
                ".agency-contact-info a.link.website",
                ".websiteurl-block a[href]",
                "a.website[href]",
            ],
            "href",
        )
        website_text = await first_text(
            page,
            [
                ".agency-contact-info .websiteurl-block a.website",
                ".agency-contact-info a.link.website",
                ".websiteurl-block a[href]",
                "a.website[href]",
            ],
        )
        agency_website = normalize_website_url(website_href or website_text)

        await random_wait(min_delay, max_delay)

        return AgentProfile(
            profile_url=seed.profile_url,
            name=clean_text(name),
            bio=clean_text(bio),
            average_sale_price=clean_text(average_sale_price),
            listings_for_sale=clean_text(listings_for_sale),
            languages=clean_text(languages),
            agency=clean_text(agency),
            phone=clean_text(phone),
            address=clean_text(address),
            city_postal_code=clean_text(city_postal_code),
            agency_website=agency_website,
        )
    finally:
        await page.close()


async def scrape_agents_to_csv(
    output_path: Path,
    start_url: str = DEFAULT_START_URL,
    max_pages: Optional[int] = None,
    max_agents: Optional[int] = None,
    min_delay: float = 1.5,
    max_delay: float = 4.0,
    timeout_ms: int = 30_000,
    headless: bool = True,
) -> int:
    """Ejecuta el scraping completo y devuelve cuantas filas se guardaron."""

    output_path.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as playwright:
        browser: Browser = await playwright.chromium.launch(headless=headless)
        context = await browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            locale="es-ES",
            timezone_id="America/Asuncion",
            viewport={"width": 1366, "height": 900},
        )

        try:
            seeds = await collect_agent_seeds(
                context=context,
                start_url=start_url,
                max_pages=max_pages,
                max_agents=max_agents,
                min_delay=min_delay,
                max_delay=max_delay,
                timeout_ms=timeout_ms,
            )

            logger.info("Total de perfiles unicos a visitar: %s", len(seeds))

            rows_written = 0
            with output_path.open("w", newline="", encoding="utf-8-sig") as csv_file:
                writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
                writer.writeheader()

                for index, seed in enumerate(seeds, start=1):
                    logger.info("[%s/%s] Perfil: %s", index, len(seeds), seed.profile_url)
                    try:
                        profile = await scrape_agent_profile(
                            context=context,
                            seed=seed,
                            min_delay=min_delay,
                            max_delay=max_delay,
                            timeout_ms=timeout_ms,
                        )
                    except Exception as exc:  # noqa: BLE001 - no queremos perder el lote.
                        logger.exception("Error extrayendo %s: %s", seed.profile_url, exc)
                        profile = AgentProfile(
                            profile_url=seed.profile_url,
                            name=seed.name,
                            bio=seed.bio,
                            listings_for_sale=seed.listings_for_sale,
                            languages=seed.languages,
                            agency=seed.agency,
                        )

                    writer.writerow(profile.to_csv_row())
                    csv_file.flush()
                    rows_written += 1

            return rows_written
        finally:
            await context.close()
            await browser.close()

"""Render the lead-gen JSONL (scrapers.leadgen_maps) into a Markdown report.

Reads ``data/raw/leadgen_maps.jsonl`` and writes a ranked, per-niche report
with ready-to-click ``wa.me`` links for mobile numbers. Pure local formatting:
it never sends anything.
"""

import json
import logging
from collections import Counter
from datetime import date
from pathlib import Path

from autobots.outreach.whatsapp_links import generate_wa_me_link

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
INPUT_PATH = PROJECT_ROOT / "data" / "raw" / "leadgen_maps.jsonl"
OUTPUT_DIR = PROJECT_ROOT / "docs" / "handbook"

NICHE_LABELS = {
    "clinica": "Clínicas / centros médicos",
    "sanatorio": "Sanatorios",
    "hospital": "Hospitales privados",
    "odontologia": "Odontología",
    "farmacia": "Farmacias",
    "laboratorio": "Laboratorios",
    "optica": "Ópticas",
    "veterinaria": "Veterinarias",
    "electronica": "Electrónica",
    "electrodomesticos": "Electrodomésticos",
    "muebleria": "Mueblerías",
    "ferreteria": "Ferreterías",
    "aseguradora": "Aseguradoras",
}

# Short openers for the pre-filled wa.me link; the full scripts live in the
# sales guide (docs/handbook/04-guia-de-venta.md).
OPENERS = {
    "clinica": "Hola! ¿Cuántos mensajes de turnos y precios responden por día? Armo sistemas que contestan eso solos por WhatsApp y avisan cuando el paciente necesita a una persona. ¿Les muestro una demo de 5 minutos?",
    "sanatorio": "Hola! ¿Cuántos mensajes de turnos y precios responden por día? Armo sistemas que contestan eso solos por WhatsApp y avisan cuando el paciente necesita a una persona. ¿Les muestro una demo de 5 minutos?",
    "hospital": "Hola! Ayudo a instituciones de salud a responder WhatsApp al instante (turnos, aranceles, estudios) y derivar solo lo importante. ¿Con quién puedo hablar 10 minutos sobre esto?",
    "odontologia": "Hola! ¿Cuántos turnos pierden por mes por responder tarde el WhatsApp? Mi sistema contesta al toque y precalifica pacientes. ¿Te muestro cómo funciona?",
    "farmacia": "Hola! ¿Se les pierden pedidos por WhatsApp en horas pico? Tengo un sistema que responde disponibilidad y delivery al instante. ¿Les interesa verlo andando?",
    "laboratorio": "Hola! ¿Cuántas veces al día responden sobre ayunos, resultados y precios? Eso se contesta solo, 24/7. ¿Les muestro una demo?",
    "optica": "Hola! ¿Cuántos mensajes de precio/stock quedan sin responder cada día? Tengo un sistema que los contesta solo. ¿Te muestro una demo por acá?",
    "veterinaria": "Hola! ¿Cuántos mensajes de turnos y consultas responden por día? Mi sistema los contesta solo y avisa cuando hay una urgencia real. ¿Te muestro una demo?",
    "electronica": "Hola! ¿Responden \"¿hay stock?\" y \"¿precio?\" cien veces por día? Armo un asistente de WhatsApp que contesta con su catálogo y avisa cuando el cliente quiere comprar. ¿Va una demo?",
    "electrodomesticos": "Hola! ¿Responden \"¿hay stock?\" y \"¿precio?\" cien veces por día? Armo un asistente de WhatsApp que contesta con su catálogo y avisa cuando el cliente quiere comprar. ¿Va una demo?",
    "muebleria": "Hola! ¿Cuántas consultas de precios y entregas responden por WhatsApp al día? Tengo un asistente que las contesta solo y deriva las ventas listas. ¿Les muestro?",
    "ferreteria": "Hola! ¿Responden precios y stock por WhatsApp todo el día? Armo un asistente que contesta al instante y le pasa el pedido armado a tu equipo. ¿Te muestro una demo?",
    "aseguradora": "Hola! ¿Cuánto tarda un cliente en recibir respuesta cuando escribe por una cotización o un siniestro? Armo asistentes de WhatsApp que responden al segundo y arman el caso para el agente. ¿Le muestro cómo quedaría?",
}
DEFAULT_OPENER = "Hola! Armo asistentes de WhatsApp que responden consultas repetitivas al instante y avisan cuando hay una venta lista. ¿Les muestro una demo de 5 minutos?"


def load_leads(path: Path = INPUT_PATH) -> list[dict]:
    leads: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                leads.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return leads


def contact_cell(lead: dict) -> str:
    """Markdown cell: wa.me link for mobiles, plain number for landlines."""
    phone = lead.get("phone")
    if not phone:
        return "sin teléfono (buscar en redes)"
    if lead.get("phone_is_mobile"):
        link = generate_wa_me_link(phone, OPENERS.get(lead.get("niche", ""), DEFAULT_OPENER))
        return f"[WhatsApp directo]({link})"
    return f"llamar +{phone}"


def build_report(leads: list[dict], today: date) -> str:
    ranked = sorted(leads, key=lambda lead: (-(lead.get("score") or 0), -(lead.get("review_count") or 0)))
    with_phone = [lead for lead in ranked if lead.get("phone")]
    mobiles = [lead for lead in with_phone if lead.get("phone_is_mobile")]
    niches = Counter(lead.get("niche", "?") for lead in ranked)

    lines = [
        f"# Leads — scraping Google Maps {today.isoformat()}",
        "",
        f"**{len(ranked)} negocios** ({len(with_phone)} con teléfono, {len(mobiles)} con celular "
        "= WhatsApp directo). Score 0–100 = volumen estimado de mensajes + facilidad de contacto. "
        "Guiones completos por nicho: `04-guia-de-venta.md`.",
        "",
        "## Por nicho",
        "",
        "| Nicho | Leads |",
        "|---|---|",
    ]
    for niche, count in niches.most_common():
        lines.append(f"| {NICHE_LABELS.get(niche, niche)} | {count} |")

    lines += [
        "",
        "## Top prospectos (ordenados por score)",
        "",
        "| # | Negocio | Nicho | Reseñas | ⭐ | Web | Contacto | Score |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, lead in enumerate(ranked[:80], 1):
        lines.append(
            f"| {i} | {lead['name']} | {NICHE_LABELS.get(lead.get('niche', ''), lead.get('niche', ''))} "
            f"| {lead.get('review_count', 0)} | {lead.get('rating') or '—'} "
            f"| {'sí' if lead.get('has_website') else '**no**'} "
            f"| {contact_cell(lead)} | **{lead.get('score', 0)}** |"
        )

    lines += [
        "",
        "> Los negocios **sin web** son doble oportunidad: automatización + landing (paquete de entrada).",
        "",
        "## Regenerar / ampliar",
        "",
        "```bash",
        "# re-scrapear (resume solo: no duplica lo ya guardado)",
        "PYTHONPATH=src python -m autobots.scrapers.leadgen_maps",
        "# regenerar este reporte",
        "PYTHONPATH=src python -m autobots.outreach.leadgen_report",
        "```",
        "",
        "Para sumar nichos o ciudades: editá `SEARCHES` en `src/autobots/scrapers/leadgen_maps.py`.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    leads = load_leads()
    if not leads:
        raise SystemExit(f"No hay leads en {INPUT_PATH} — corré primero el scraper.")
    today = date.today()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"03-leads-{today.isoformat()}.md"
    output_path.write_text(build_report(leads, today), encoding="utf-8")
    logger.info("Reporte: %s (%d leads)", output_path, len(leads))


if __name__ == "__main__":
    main()

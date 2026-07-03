#!/usr/bin/env python3
"""CLI para scrapear agentes de Properstar y exportarlos a CSV."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

DEFAULT_START_URL = (
    "https://www.properstar.es/paraguay/asuncion-l2/agentes-inmobiliarios"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrapea agentes inmobiliarios de Properstar y guarda CSV."
    )
    parser.add_argument(
        "--start-url",
        default=DEFAULT_START_URL,
        help="URL del listado inicial de Properstar.",
    )
    parser.add_argument(
        "--output",
        default="agentes_properstar.csv",
        help="Ruta del CSV de salida.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Limite de paginas de listado. Por defecto avanza hasta no encontrar nuevos perfiles.",
    )
    parser.add_argument(
        "--max-agents",
        type=int,
        default=None,
        help="Limite opcional de perfiles a visitar.",
    )
    parser.add_argument(
        "--min-delay",
        type=float,
        default=1.5,
        help="Espera minima aleatoria entre navegaciones.",
    )
    parser.add_argument(
        "--max-delay",
        type=float,
        default=4.0,
        help="Espera maxima aleatoria entre navegaciones.",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=30_000,
        help="Timeout de navegacion en milisegundos.",
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Muestra el navegador. Util para debug si el sitio bloquea headless.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.min_delay < 0 or args.max_delay < args.min_delay:
        raise SystemExit("--max-delay debe ser mayor o igual a --min-delay")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    from autobots.scrapers.properstar_agents import scrape_agents_to_csv

    rows = asyncio.run(
        scrape_agents_to_csv(
            output_path=Path(args.output),
            start_url=args.start_url,
            max_pages=args.max_pages,
            max_agents=args.max_agents,
            min_delay=args.min_delay,
            max_delay=args.max_delay,
            timeout_ms=args.timeout_ms,
            headless=not args.headful,
        )
    )

    print(f"CSV generado: {args.output} ({rows} agentes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

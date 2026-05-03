#!/usr/bin/env python3
"""CLI for processing scraped leads into a WhatsApp outreach CSV."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autobots.leads.models import SUPPORTED_NICHES
from autobots.leads.pipeline import process_leads_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Process raw business leads into scored WhatsApp outreach CSV files."
    )
    parser.add_argument("--input", required=True, help="Input CSV or JSON file.")
    parser.add_argument("--output", required=True, help="Output processed CSV file.")
    parser.add_argument("--niche", required=True, choices=SUPPORTED_NICHES, help="Target niche.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of leads to export.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    processed = process_leads_file(
        input_path=args.input,
        output_path=args.output,
        niche=args.niche,
        limit=args.limit,
    )

    print(f"Processed {len(processed)} leads")
    print(f"Output written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Small file IO helpers used by scripts and notebooks."""

import csv
import json
from pathlib import Path
from typing import Any, Iterable


def read_json(path: str | Path) -> Any:
    """Read a UTF-8 JSON file."""
    with Path(path).open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: str | Path, data: Any, *, indent: int = 2) -> None:
    """Write a UTF-8 JSON file and create parent directories."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=indent)


def read_csv(path: str | Path) -> list[dict[str, str]]:
    """Read a UTF-8 CSV file as dictionaries."""
    with Path(path).open("r", encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: str | Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    """Write dictionaries to a UTF-8 CSV file and create parent directories."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

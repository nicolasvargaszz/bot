"""Streamlit dashboard for reviewing processed leads before manual outreach."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"

EDITABLE_STATUSES = (
    "new",
    "contacted",
    "replied",
    "interested",
    "demo_sent",
    "closed",
    "lost",
    "do_not_contact",
)

NICHE_OPTIONS = ("all", "real_estate", "retail", "clinics", "beauty", "unknown")
DEFAULT_COLUMNS = [
    "name",
    "normalized_phone",
    "category",
    "city",
    "score",
    "priority",
    "status",
]


def list_processed_csv_files(data_dir: Path = PROCESSED_DATA_DIR) -> list[Path]:
    """Return processed CSV files available for review."""
    if not data_dir.exists():
        return []
    return sorted(path for path in data_dir.glob("*.csv") if path.is_file())


def infer_niche_from_filename(path: Path) -> str:
    """Infer niche from a processed CSV filename when the column is missing."""
    filename = path.name.lower()
    for niche in ("real_estate", "retail", "clinics", "beauty"):
        if niche in filename:
            return niche
    return "unknown"


def load_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    """Load a CSV file and ensure the status column exists."""
    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        fieldnames = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]

    if "status" not in fieldnames:
        fieldnames.append("status")

    for row in rows:
        row.setdefault("status", "new")
        if not row["status"]:
            row["status"] = "new"
        if row["status"] == "pending":
            row["status"] = "new"

    return rows, fieldnames


def save_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    """Persist updated lead rows to CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def get_row_niche(row: dict[str, str], fallback_niche: str) -> str:
    """Read niche from a row or use the filename-derived fallback."""
    return (row.get("niche") or fallback_niche or "unknown").strip() or "unknown"


def parse_score(row: dict[str, str]) -> int:
    """Parse score as an integer for filtering."""
    try:
        return int(float(row.get("score") or 0))
    except ValueError:
        return 0


def unique_values(rows: list[dict[str, str]], field: str) -> list[str]:
    """Return sorted non-empty values for a filter field."""
    values = {str(row.get(field, "")).strip() for row in rows if str(row.get(field, "")).strip()}
    return sorted(values)


def apply_filters(
    rows: list[dict[str, str]],
    *,
    fallback_niche: str,
    niche: str,
    priorities: list[str],
    cities: list[str],
    statuses: list[str],
    score_range: tuple[int, int],
) -> list[tuple[int, dict[str, str]]]:
    """Filter rows and keep their original row indexes for saving edits."""
    filtered: list[tuple[int, dict[str, str]]] = []
    min_score, max_score = score_range

    for index, row in enumerate(rows):
        row_niche = get_row_niche(row, fallback_niche)
        row_score = parse_score(row)

        if niche != "all" and row_niche != niche:
            continue
        if priorities and row.get("priority", "") not in priorities:
            continue
        if cities and row.get("city", "") not in cities:
            continue
        if statuses and row.get("status", "") not in statuses:
            continue
        if not min_score <= row_score <= max_score:
            continue

        filtered.append((index, row))

    return filtered


def table_rows(rows: list[tuple[int, dict[str, str]]], fallback_niche: str) -> list[dict[str, Any]]:
    """Build compact rows for the visible table."""
    visible_rows = []
    for index, row in rows:
        visible_row = {
            "row": index + 1,
            "niche": get_row_niche(row, fallback_niche),
        }
        for column in DEFAULT_COLUMNS:
            visible_row[column] = row.get(column, "")
        visible_rows.append(visible_row)
    return visible_rows


def lead_label(index: int, row: dict[str, str]) -> str:
    """Build a readable selectbox label."""
    name = row.get("name") or "Unnamed lead"
    score = row.get("score") or "0"
    priority = row.get("priority") or "unknown"
    city = row.get("city") or "unknown city"
    return f"#{index + 1} | {score} | {priority} | {name} | {city}"


def render_lead_details(row_index: int, row: dict[str, str], csv_path: Path, fieldnames: list[str]) -> None:
    """Render selected lead details and local status editor."""
    st.subheader(row.get("name") or "Selected Lead")

    detail_columns = st.columns(2)
    with detail_columns[0]:
        st.write("**Phone:**", row.get("phone") or "-")
        st.write("**Normalized phone:**", row.get("normalized_phone") or "-")
        st.write("**Category:**", row.get("category") or "-")
        st.write("**City:**", row.get("city") or "-")
    with detail_columns[1]:
        st.write("**Score:**", row.get("score") or "-")
        st.write("**Priority:**", row.get("priority") or "-")
        st.write("**Status:**", row.get("status") or "new")
        if row.get("source_url"):
            st.link_button("Open source", row["source_url"])

    st.markdown("#### Suggested Outreach Message")
    st.text_area(
        "Suggested message",
        value=row.get("suggested_message") or "",
        height=150,
        label_visibility="collapsed",
        disabled=True,
    )

    whatsapp_link = row.get("whatsapp_link") or ""
    if whatsapp_link:
        st.link_button("Open WhatsApp link", whatsapp_link)
    else:
        st.warning("This lead does not have a WhatsApp link.")

    st.markdown("#### Update Status")
    current_status = row.get("status") or "new"
    current_index = EDITABLE_STATUSES.index(current_status) if current_status in EDITABLE_STATUSES else 0
    new_status = st.selectbox("Status", EDITABLE_STATUSES, index=current_index)

    if st.button("Save updated CSV", type="primary"):
        st.session_state.lead_rows[row_index]["status"] = new_status
        save_csv(csv_path, st.session_state.lead_rows, fieldnames)
        st.success(f"Saved status as '{new_status}'.")


def main() -> None:
    st.set_page_config(page_title="Autobots Lead Review", layout="wide")
    st.title("Autobots Lead Review")
    st.caption("Manual lead inspection dashboard. This app does not send WhatsApp messages.")

    csv_files = list_processed_csv_files()
    if not csv_files:
        st.info("No processed CSV files found in data/processed.")
        st.code(
            ".venv/bin/python src/scripts/process_leads.py "
            "--input data/raw/real_estate_leads.csv "
            "--output data/processed/top_real_estate_leads.csv "
            "--niche real_estate --limit 100"
        )
        return

    selected_file = st.sidebar.selectbox(
        "Processed CSV",
        csv_files,
        format_func=lambda path: path.name,
    )

    if st.session_state.get("selected_csv_path") != str(selected_file):
        rows, fieldnames = load_csv(selected_file)
        st.session_state.selected_csv_path = str(selected_file)
        st.session_state.lead_rows = rows
        st.session_state.fieldnames = fieldnames

    rows = st.session_state.lead_rows
    fieldnames = st.session_state.fieldnames
    fallback_niche = infer_niche_from_filename(selected_file)

    st.sidebar.markdown("### Filters")
    niche_filter = st.sidebar.selectbox("Niche", NICHE_OPTIONS)
    priority_filter = st.sidebar.multiselect("Priority", unique_values(rows, "priority"))
    city_filter = st.sidebar.multiselect("City", unique_values(rows, "city"))
    status_filter = st.sidebar.multiselect("Status", unique_values(rows, "status"))
    score_range = st.sidebar.slider("Score range", 0, 100, (0, 100))

    filtered_rows = apply_filters(
        rows,
        fallback_niche=fallback_niche,
        niche=niche_filter,
        priorities=priority_filter,
        cities=city_filter,
        statuses=status_filter,
        score_range=score_range,
    )

    total_count = len(rows)
    filtered_count = len(filtered_rows)
    high_count = sum(1 for _, row in filtered_rows if row.get("priority") == "high")

    metric_columns = st.columns(3)
    metric_columns[0].metric("Total leads", total_count)
    metric_columns[1].metric("Filtered leads", filtered_count)
    metric_columns[2].metric("High priority", high_count)

    st.subheader("Leads")
    st.dataframe(table_rows(filtered_rows, fallback_niche), use_container_width=True, hide_index=True)

    if not filtered_rows:
        st.warning("No leads match the selected filters.")
        return

    selected_index = st.selectbox(
        "Select lead",
        options=[index for index, _ in filtered_rows],
        format_func=lambda index: lead_label(index, rows[index]),
    )

    render_lead_details(selected_index, rows[selected_index], selected_file, fieldnames)


if __name__ == "__main__":
    main()

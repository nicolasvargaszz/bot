"""Pilot report rendering: totals, out-of-hours math, and edge cases."""

import argparse

import pytest

from autobots.reporting.pilot_report import (
    _parse_business_hours,
    build_pilot_report,
    parse_args,
)


def _daily_rows() -> list[dict[str, int | str]]:
    return [
        {
            "date": "2026-07-01",
            "buffered": 40,
            "flushes": 16,
            "fragments_flushed": 40,
            "audio_messages": 3,
            "duplicates": 2,
            "forward_ok": 15,
            "forward_failed": 1,
            "dlq_redelivered": 1,
            "dlq_dropped": 0,
        },
        {
            "date": "2026-07-02",
            "buffered": 60,
            "flushes": 24,
            "fragments_flushed": 60,
            "audio_messages": 5,
            "duplicates": 0,
            "forward_ok": 24,
            "forward_failed": 0,
            "dlq_redelivered": 0,
            "dlq_dropped": 0,
        },
    ]


def test_report_includes_totals_and_averages():
    report = build_pilot_report("demo", _daily_rows(), {10: 80, 20: 20})

    assert "# Reporte del piloto — demo" in report
    assert "100 mensajes" in report  # 40 + 60
    assert "40 conversaciones" in report  # 16 + 24
    assert "2,5 mensajes seguidos" in report or "2.5 mensajes seguidos" in report


def test_out_of_hours_share_uses_business_hours():
    # 80 messages at 10:00 (inside 8-18), 20 at 20:00 (outside) -> 20%
    report = build_pilot_report("demo", _daily_rows(), {10: 80, 20: 20}, business_hours=(8, 18))

    assert "20% de los mensajes llegaron fuera del horario" in report
    assert "08:00–18:00" in report


def test_no_lost_messages_note_when_nothing_dropped():
    report = build_pilot_report("demo", _daily_rows(), {10: 100})

    assert "Ningún mensaje se perdió" in report


def test_dropped_messages_are_flagged():
    rows = _daily_rows()
    rows[0]["dlq_dropped"] = 2

    report = build_pilot_report("demo", rows, {10: 100})

    assert "2 mensajes no pudieron entregarse" in report
    assert "Ningún mensaje se perdió" not in report


def test_peak_hours_listed_in_descending_order():
    report = build_pilot_report("demo", _daily_rows(), {9: 5, 11: 30, 15: 12})

    peak_section = report.split("## Horas pico")[1].split("##")[0]
    assert peak_section.index("11:00") < peak_section.index("15:00") < peak_section.index("09:00")


def test_empty_metrics_do_not_crash():
    report = build_pilot_report("demo", [], {})

    assert "sin datos" in report


def test_business_hours_parser_accepts_valid_range():
    assert _parse_business_hours("08-18") == (8, 18)


def test_business_hours_parser_rejects_inverted_range():
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_business_hours("18-08")


def test_parse_args_requires_instance():
    with pytest.raises(SystemExit):
        parse_args([])

    args = parse_args(["--instance", "demo", "--days", "14"])
    assert args.instance == "demo"
    assert args.days == 14
    assert args.business_hours == (8, 18)

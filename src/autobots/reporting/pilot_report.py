"""Generate the Spanish pilot report for a client review call.

Reads the per-instance counters the message buffer service records in Redis
(see `autobots.services.message_buffer.metrics`) and renders a Markdown
report a business owner can read: messages handled, instant replies,
out-of-hours share, peak hours, and reliability.

Usage:
    PYTHONPATH=src python -m autobots.reporting.pilot_report \
        --instance cliente-main --days 7 --business-hours 08-18
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime

from redis.asyncio import Redis

from autobots.services.message_buffer.config import get_settings
from autobots.services.message_buffer.metrics import MetricsRecorder


def _fmt(value: int) -> str:
    """Format an integer with dot thousands separators (es-PY convention)."""
    return f"{value:,}".replace(",", ".")


def _dec(value: float) -> str:
    """Format a one-decimal float with a comma (es-PY convention)."""
    return f"{value:.1f}".replace(".", ",")


def _plural(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural


def _sum(daily: list[dict[str, int | str]], field: str) -> int:
    return sum(int(row.get(field, 0)) for row in daily)


def build_pilot_report(
    instance: str,
    daily: list[dict[str, int | str]],
    hourly: dict[int, int],
    business_hours: tuple[int, int] = (8, 18),
    generated_at: datetime | None = None,
) -> str:
    """Render the pilot report as Spanish Markdown from metric rows."""
    generated_at = generated_at or datetime.now(UTC)
    days = len(daily)
    open_hour, close_hour = business_hours

    buffered = _sum(daily, "buffered")
    flushes = _sum(daily, "flushes")
    fragments = _sum(daily, "fragments_flushed")
    audio = _sum(daily, "audio_messages")
    duplicates = _sum(daily, "duplicates")
    forward_ok = _sum(daily, "forward_ok")
    forward_failed = _sum(daily, "forward_failed")
    redelivered = _sum(daily, "dlq_redelivered")
    dropped = _sum(daily, "dlq_dropped")

    total_by_hour = sum(hourly.values())
    out_of_hours = sum(
        count for hour, count in hourly.items() if not open_hour <= hour < close_hour
    )
    out_pct = round(100 * out_of_hours / total_by_hour) if total_by_hour else 0
    avg_per_day = round(buffered / days, 1) if days else 0.0
    avg_fragments = round(fragments / flushes, 1) if flushes else 0.0
    peak_hours = [
        (hour, count)
        for hour, count in sorted(hourly.items(), key=lambda item: item[1], reverse=True)
        if count > 0
    ][:3]

    period = f"{daily[0]['date']} al {daily[-1]['date']}" if daily else "sin datos"

    lines: list[str] = [
        f"# Reporte del piloto — {instance}",
        "",
        f"Período: **{period}** ({days} días) · Generado: "
        f"{generated_at.strftime('%Y-%m-%d %H:%M')} UTC",
        "",
        "## Resumen",
        "",
        f"- **{_fmt(buffered)} {_plural(buffered, 'mensaje recibido', 'mensajes recibidos')}** "
        f"por WhatsApp (promedio {_dec(avg_per_day)} por día).",
        f"- **{_fmt(flushes)} {_plural(flushes, 'conversación atendida', 'conversaciones atendidas')} "
        f"al instante**, combinando en promedio {_dec(avg_fragments)} mensajes seguidos "
        "en una sola respuesta.",
    ]

    if total_by_hour:
        lines.append(
            f"- **{out_pct}% de los mensajes llegaron fuera del horario de atención** "
            f"({open_hour:02d}:00–{close_hour:02d}:00). Antes, esas consultas esperaban "
            "hasta el día siguiente; ahora se responden igual."
        )
    if audio:
        lines.append(f"- **{_fmt(audio)} notas de voz** procesadas.")
    if duplicates:
        lines.append(
            f"- {_fmt(duplicates)} mensajes duplicados detectados y descartados "
            "(nadie recibió respuestas repetidas)."
        )

    lines += ["", "## Confiabilidad", ""]
    lines.append(
        f"- {_fmt(forward_ok)} "
        f"{_plural(forward_ok, 'entrega procesada', 'entregas procesadas')} sin reintentos."
    )
    if forward_failed or redelivered:
        lines.append(
            f"- {_fmt(forward_failed)} "
            f"{_plural(forward_failed, 'entrega falló', 'entregas fallaron')} al primer intento; "
            f"{_fmt(redelivered)} se "
            f"{_plural(redelivered, 'recuperó', 'recuperaron')} "
            "automáticamente con la cola de reintentos."
        )
    if dropped:
        lines.append(
            f"- **{_fmt(dropped)} mensajes no pudieron entregarse** después de agotar "
            "los reintentos — revisar con el equipo técnico."
        )
    else:
        lines.append("- **Ningún mensaje se perdió** en el período.")

    if peak_hours:
        lines += ["", "## Horas pico", ""]
        for hour, count in peak_hours:
            lines.append(f"- {hour:02d}:00–{hour + 1:02d}:00 → {_fmt(count)} mensajes")

    lines += [
        "",
        "## Detalle por día",
        "",
        "| Fecha | Mensajes | Conversaciones | Notas de voz |",
        "|---|---|---|---|",
    ]
    for row in daily:
        lines.append(
            f"| {row['date']} | {_fmt(int(row.get('buffered', 0)))} "
            f"| {_fmt(int(row.get('flushes', 0)))} "
            f"| {_fmt(int(row.get('audio_messages', 0)))} |"
        )

    lines += [
        "",
        "---",
        "",
        "*Mensajes = mensajes entrantes de clientes. Conversaciones = ráfagas de "
        "mensajes respondidas como una sola consulta. Los datos provienen del "
        "registro operativo del sistema; no incluyen el contenido de los mensajes.*",
        "",
    ]
    return "\n".join(lines)


def _parse_business_hours(raw: str) -> tuple[int, int]:
    try:
        open_str, close_str = raw.split("-", 1)
        open_hour, close_hour = int(open_str), int(close_str)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "business hours must look like 08-18 (open-close, 0-24)"
        ) from exc
    if not (0 <= open_hour < close_hour <= 24):
        raise argparse.ArgumentTypeError("business hours must satisfy 0 <= open < close <= 24")
    return open_hour, close_hour


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate the Spanish pilot report from message-buffer metrics."
    )
    parser.add_argument("--instance", required=True, help="Evolution instance name, e.g. cliente-main")
    parser.add_argument("--days", type=int, default=7, help="Days to include (default 7)")
    parser.add_argument(
        "--business-hours",
        type=_parse_business_hours,
        default=(8, 18),
        help="Client business hours as open-close, e.g. 08-18 (default)",
    )
    parser.add_argument("--redis-url", default="", help="Override REDIS_URL from the environment")
    parser.add_argument("--output", default="", help="Write to this file instead of stdout")
    return parser.parse_args(argv)


async def generate(args: argparse.Namespace) -> str:
    settings = get_settings()
    redis = Redis.from_url(args.redis_url or settings.redis_url, decode_responses=True)
    try:
        recorder = MetricsRecorder(redis, settings)
        daily = await recorder.read_daily(args.instance, args.days)
        hourly = await recorder.read_hourly_totals(args.instance, args.days)
    finally:
        await redis.aclose()
    return build_pilot_report(args.instance, daily, hourly, args.business_hours)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = asyncio.run(generate(args))
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(report)
        print(f"Report written to {args.output}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())

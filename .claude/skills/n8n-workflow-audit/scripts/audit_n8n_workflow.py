#!/usr/bin/env python3
"""Audit n8n workflow JSON exports before committing or importing them.

Checks:
  1. JSON parses and every connection endpoint references an existing node.
  2. No hardcoded credentials (API-key shapes, bot tokens, keys in URLs).
  3. No unresolved placeholders (TU_..., YOUR_..., CHANGEME, TODO).
  4. Webhook-triggered workflows verify a shared secret somewhere.
  5. No operational metadata that identifies a live instance
     (meta.instanceId, credential IDs, pinData/execution data).

Usage:
  python audit_n8n_workflow.py <workflow.json> [more.json ...]
  python audit_n8n_workflow.py n8n/workflows/*.json

Exit code 0 = clean, 1 = findings.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SECRET_PATTERNS: list[tuple[str, str]] = [
    (r"AIza[0-9A-Za-z_\-]{20,}", "Google API key"),
    (r"\b\d{8,10}:[A-Za-z0-9_\-]{30,}\b", "Telegram bot token"),
    (r"\bsk-[A-Za-z0-9]{20,}\b", "OpenAI-style secret key"),
    (r"\bntn_[A-Za-z0-9]{20,}\b", "Notion token"),
    (r"\bxox[bpars]-[A-Za-z0-9\-]{10,}\b", "Slack token"),
    (r"Bearer\s+(?!\{\{)[A-Za-z0-9_\-\.]{20,}", "literal Bearer token"),
    (r"[?&](key|apikey|api_key|token)=(?!\{\{|<|\$)[A-Za-z0-9_\-]{12,}", "credential in URL query"),
]

PLACEHOLDER_PATTERN = re.compile(r"\b(TU_[A-Z_]+|YOUR_[A-Z_]+|CHANGEME|REPLACE_ME|TODO)\b")

# Header params named like a key whose value is a literal, not an expression.
LITERAL_AUTH_HEADER = re.compile(
    r'"name":\s*"(apikey|api-key|authorization|x-api-key)",\s*"value":\s*"(?!=)(?!\{\{)[^"]{8,}"',
    re.IGNORECASE,
)


def audit(path: Path) -> list[str]:
    findings: list[str] = []
    raw = path.read_text(encoding="utf-8")

    try:
        wf = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [f"invalid JSON: {exc}"]

    nodes = wf.get("nodes", [])
    names = {n.get("name") for n in nodes}

    # 1. Connection integrity
    for src, outputs in wf.get("connections", {}).items():
        if src not in names:
            findings.append(f"connection source references missing node {src!r}")
        for branch in outputs.get("main", []):
            for link in branch or []:
                if link.get("node") not in names:
                    findings.append(
                        f"connection from {src!r} targets missing node {link.get('node')!r}"
                    )

    # 2. Hardcoded credentials
    for pattern, label in SECRET_PATTERNS:
        for match in re.finditer(pattern, raw):
            findings.append(f"possible {label}: {match.group(0)[:40]!r}")
    for match in LITERAL_AUTH_HEADER.finditer(raw):
        findings.append(f"literal auth header value: {match.group(0)[:60]!r}")

    # 3. Placeholders
    for match in sorted(set(PLACEHOLDER_PATTERN.findall(raw))):
        findings.append(f"unresolved placeholder: {match}")

    # 4. Webhook secret verification
    node_types = {n.get("type", "") for n in nodes}
    if "n8n-nodes-base.webhook" in node_types and "WEBHOOK_SECRET" not in raw:
        findings.append(
            "webhook trigger present but no *_WEBHOOK_SECRET check found - "
            "anyone who discovers the URL can invoke this workflow"
        )

    # 5. Operational metadata
    instance_id = (wf.get("meta") or {}).get("instanceId", "")
    if re.fullmatch(r"[a-f0-9]{16,}", str(instance_id)):
        findings.append(f"meta.instanceId identifies a live n8n instance: {instance_id[:16]}…")
    if wf.get("pinData"):
        findings.append("pinData present - may contain real conversation/customer data")
    for node in nodes:
        for cred in (node.get("credentials") or {}).values():
            if isinstance(cred, dict) and cred.get("id"):
                findings.append(
                    f"node {node.get('name')!r} carries credential id {cred['id']!r} "
                    "(operational metadata; strip before committing)"
                )

    return findings


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2

    dirty = False
    for arg in argv:
        path = Path(arg)
        findings = audit(path)
        if findings:
            dirty = True
            print(f"FAIL {path}")
            for finding in findings:
                print(f"  - {finding}")
        else:
            print(f"ok   {path}")
    return 1 if dirty else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

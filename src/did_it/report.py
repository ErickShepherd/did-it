"""Render receipts to a human/CI-readable report and compute the exit code.

Design: docs/design/did-it.md — per-claim receipt table + session summary; non-zero exit only on
CONTRADICTED (abstention is never failure).
"""

from __future__ import annotations

from collections import Counter

from .verdicts import FAILING_VERDICTS, Receipt


def render(receipts: list[Receipt]) -> str:
    """Per-claim receipt table + summary line."""
    if not receipts:
        return "did-it: no checkable claims found.\n"
    lines = []
    width = max(len(r.verdict.value) for r in receipts)
    for r in receipts:
        evidence = r.evidence_ref or "-"
        lines.append(f"{r.verdict.value:<{width}}  [{evidence}]  {r.claim_text}")
        for note in r.notes:
            lines.append(f"{'':<{width}}      · {note}")
    counts = Counter(r.verdict.value for r in receipts)
    summary = " · ".join(f"{v}: {n}" for v, n in sorted(counts.items()))
    lines.append("")
    lines.append(f"did-it: {len(receipts)} claim(s) — {summary}")
    return "\n".join(lines) + "\n"


def exit_code(receipts: list[Receipt]) -> int:
    """0 unless any receipt carries a failing verdict (CONTRADICTED)."""
    return 1 if any(r.verdict in FAILING_VERDICTS for r in receipts) else 0


__all__ = ["render", "exit_code", "FAILING_VERDICTS"]

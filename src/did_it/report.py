"""Render receipts to a human/CI-readable report and compute the exit code.

Design: docs/design/did-it.md — per-claim receipt table + session summary; non-zero exit only on
CONTRADICTED (abstention is never failure).
"""

from __future__ import annotations

import re
from collections import Counter

from .verdicts import FAILING_VERDICTS, Receipt

#: Claim text and notes are untrusted transcript content rendered to a terminal: C0/C1
#: controls (ANSI cursor-up/erase can visually rewrite a CONTRADICTED row) and Unicode
#: bidi overrides are neutralized; a newline would forge a whole receipt row (panel C6).
#: The range spans U+2028 (LINE SEP) and U+2029 (PARAGRAPH SEP) \u2014 many terminals treat both
#: as hard breaks, so like `\n` they could forge a row; the real writer (Node JSON.stringify)
#: emits them raw (testing.py) so they reach here unescaped (audit 2026-07-10).
_UNSAFE = re.compile(r"[\x00-\x08\x0a-\x1f\x7f-\x9f\u2028-\u202e\u2066-\u2069]")


def _sanitize(text: str) -> str:
    return _UNSAFE.sub("�", text)


def render(receipts: list[Receipt]) -> str:
    """Per-claim receipt table + summary line."""
    if not receipts:
        return "did-it: no checkable claims found.\n"
    lines = []
    width = max(len(r.verdict.value) for r in receipts)
    for r in receipts:
        evidence = _sanitize(r.evidence_ref or "-")
        lines.append(f"{r.verdict.value:<{width}}  [{evidence}]  {_sanitize(r.claim_text)}")
        for note in r.notes:
            lines.append(f"{'':<{width}}      · {_sanitize(note)}")
    counts = Counter(r.verdict.value for r in receipts)
    summary = " · ".join(f"{v}: {n}" for v, n in sorted(counts.items()))
    lines.append("")
    lines.append(f"did-it: {len(receipts)} claim(s) — {summary}")
    return "\n".join(lines) + "\n"


def exit_code(receipts: list[Receipt]) -> int:
    """0 unless any receipt carries a failing verdict (CONTRADICTED)."""
    return 1 if any(r.verdict in FAILING_VERDICTS for r in receipts) else 0


__all__ = ["render", "exit_code", "FAILING_VERDICTS"]

#!/usr/bin/env python3
"""Mechanical privacy leak-gate (design doc D8).

Blocks committing private content in fixtures/eval material. Run by pre-commit and CI. This is
infrastructure, not part of the (unbuilt) did-it pipeline, so it is implemented.

Checks each given path (default: everything under fixtures/):
  * deny private path patterns, obvious secrets, and emails;
  * require the `FIXTURES_ONLY` marker in committed fixture files.

Exit non-zero (and print offending files) on any violation.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DENY = [
    re.compile(r"/home/[a-z]", re.I),
    re.compile(r"/Users/[A-Za-z]"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                 # AWS key id
    re.compile(r"\b(secret|password|passwd|api[_-]?key|token)\s*[:=]", re.I),
    re.compile(r"[A-Za-z0-9._%+-]+@(?!example\.)[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),  # email (allow example.*)
]
MARKER = "FIXTURES_ONLY"


def iter_targets(argv: list[str]) -> list[Path]:
    if argv:
        return [Path(a) for a in argv]
    root = Path("fixtures")
    return [p for p in root.rglob("*") if p.is_file()] if root.exists() else []


def scan(path: Path) -> list[str]:
    problems: list[str] = []
    try:
        text = path.read_text(errors="replace")
    except OSError as e:  # unreadable -> surface, don't silently pass
        return [f"{path}: unreadable ({e})"]
    for pat in DENY:
        if pat.search(text):
            problems.append(f"{path}: matches deny pattern /{pat.pattern}/")
    if path.suffix in {".json", ".jsonl"} and "fixtures" in path.parts and MARKER not in text:
        problems.append(f"{path}: missing required '{MARKER}' marker")
    return problems


def main(argv: list[str]) -> int:
    problems: list[str] = []
    for path in iter_targets(argv):
        problems += scan(path)
    if problems:
        print("LEAK-GATE FAILED:", file=sys.stderr)
        for p in problems:
            print("  " + p, file=sys.stderr)
        return 1
    print("leak-gate: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

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

#: "Known repo names" denylist (design doc D8 + fixtures/README.md, which forbid "real repo
#: names"). The names themselves are the owner's PRIVATE project/employer list — they must never
#: be committed, so they live in this gitignored local file (one name per line; `#` comments and
#: blank lines ignored). This module supplies only the MECHANISM; the owner supplies the content.
#: Absent file -> no extra patterns (the check is a no-op until names are provided). Matching is
#: substring + case-insensitive: any occurrence of a private name flags the file, the
#: privacy-conservative choice (the owner tunes the list). Added by the audit loop 2026-07-10.
LOCAL_NAMES_FILE = Path(__file__).with_name(".leakgate-names.local")


def load_local_name_patterns(path: Path = LOCAL_NAMES_FILE) -> list[re.Pattern[str]]:
    """Compile the owner's gitignored known-names denylist into case-insensitive patterns.

    Missing/unreadable file -> [] (no-op): the mechanism is present with or without names.
    """
    try:
        raw = path.read_text(errors="replace")
    except OSError:
        return []
    patterns: list[re.Pattern[str]] = []
    for line in raw.splitlines():
        name = line.strip()
        if not name or name.startswith("#"):
            continue
        patterns.append(re.compile(re.escape(name), re.I))
    return patterns


def iter_targets(argv: list[str]) -> list[Path]:
    if argv:
        return [Path(a) for a in argv]
    root = Path("fixtures")
    return [p for p in root.rglob("*") if p.is_file()] if root.exists() else []


def scan(path: Path, extra_deny: list[re.Pattern[str]] | None = None) -> list[str]:
    problems: list[str] = []
    try:
        text = path.read_text(errors="replace")
    except OSError as e:  # unreadable -> surface, don't silently pass
        return [f"{path}: unreadable ({e})"]
    for pat in (*DENY, *(extra_deny or [])):
        if pat.search(text):
            problems.append(f"{path}: matches deny pattern /{pat.pattern}/")
    # Every committed file under fixtures/ must carry the marker, not just .json/.jsonl — a
    # .log/.txt/extensionless fixture was silently exempt (matches the README's
    # "Every committed fixture" rule). README.md carries the marker in its prose, so it passes.
    if "fixtures" in path.parts and MARKER not in text:
        problems.append(f"{path}: missing required '{MARKER}' marker")
    return problems


def main(argv: list[str]) -> int:
    extra_deny = load_local_name_patterns()
    problems: list[str] = []
    for path in iter_targets(argv):
        problems += scan(path, extra_deny)
    if problems:
        print("LEAK-GATE FAILED:", file=sys.stderr)
        for p in problems:
            print("  " + p, file=sys.stderr)
        return 1
    print("leak-gate: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

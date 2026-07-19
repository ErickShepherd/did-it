#!/usr/bin/env python3
"""Mechanical privacy leak-gate (design doc D8).

Blocks committing private content. Two scans: (1) a per-file DENY + FIXTURES_ONLY-marker check over
`fixtures/` (or any explicit path argument), run by pre-commit (`files: ^fixtures/`) and CI; and
(2) a repo-wide *structural* scan of the whole tracked tree (`git ls-files`) for real home paths
and concrete key shapes, run on the no-arg CI/release invocation — this catches private data in
docs/ or scripts/ that the fixtures-only default would miss. This is infrastructure — the privacy
gate — separate from the did-it verification pipeline.

Two-tier check over each path given (default: everything under `fixtures/`):
  * DENY private path patterns, obvious secrets, and emails — applied to EVERY scanned path;
  * require the `FIXTURES_ONLY` marker — ONLY for files under `fixtures/`. The marker affirms
    "fabricated fixture" (README rule: "every committed *fixture*"), so ordinary source and any
    eval material outside `fixtures/` are DENY-scanned when passed but not marker-checked.

Exit non-zero (and print offending files) on any violation.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

DENY = [
    re.compile(r"/home/[a-z]", re.I),
    re.compile(r"/Users/[A-Za-z]"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                 # AWS access key id
    re.compile(r"\bASIA[0-9A-Z]{16}\b"),                 # AWS temporary (STS) key id
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),   # PEM private key block
    re.compile(r"\bghp_[0-9A-Za-z]{36}\b"),              # GitHub personal access token
    re.compile(r"\bgithub_pat_[0-9A-Za-z_]{22,}\b"),     # GitHub fine-grained PAT
    re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b"),     # Slack token
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),           # Google API key
    # Allow an optional closing quote after the keyword so the JSON/JSONL form `"token": "abc"`
    # (every fixture's shape) is caught, not just the bare `token: abc` colon form.
    re.compile(r"\b(secret|password|passwd|api[_-]?key|token)[\"']?\s*[:=]", re.I),
    re.compile(r"[A-Za-z0-9._%+-]+@(?!example\.)[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),  # email (allow example.*)
]
MARKER = "FIXTURES_ONLY"

#: "Known repo names" denylist (design doc D8 + fixtures/README.md, which forbid "real repo
#: names"). The names themselves are the owner's PRIVATE project/employer list — they must never
#: be committed, so they live in this gitignored local file (one name per line; `#` comments and
#: blank lines ignored). This module supplies only the MECHANISM; the owner supplies the content.
#: Absent file -> no extra patterns (the check is a no-op until names are provided). Matching is
#: substring + case-insensitive: any occurrence of a private name flags the file, the
#: privacy-conservative choice (the owner tunes the list).
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


# --- Repo-wide structural leak scan (design doc D8) --------------------------------------------
# The no-arg run (CI/release) scans the whole tracked tree for near-zero-FP structural leaks,
# closing the gap where private data in docs/ or scripts/ escaped the fixtures-only default (a real
# /home/<user> path shipped in operations docs). Only unambiguous shapes go here; the loose
# secret/token *keyword*, generic email, and owner-name patterns stay fixtures/explicit-only (they
# also match ordinary source like `token: str` and the project's own public contact address).
HOME_PLACEHOLDERS = frozenset(
    {"user", "youruser", "alice", "bob", "carol", "example", "runner", "ci"}
)
_HOME_RE = re.compile(r"/(?:home|Users)/([A-Za-z][A-Za-z0-9._-]*)")
STRUCTURAL_DENY = [
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bASIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bghp_[0-9A-Za-z]{36}\b"),
    re.compile(r"\bgithub_pat_[0-9A-Za-z_]{22,}\b"),
    re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
]
#: Files that legitimately embed sample home paths and token *shapes* — the gate's own code and
#: its tests. Skipped entirely by the structural scan (they are reviewed as the gate itself).
STRUCTURAL_EXEMPT = frozenset({"scripts/leak_gate.py", "tests/test_leak_gate.py"})
#: Binary/asset suffixes skipped by the tracked-tree walk.
_BINARY_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".whl", ".gz", ".zip", ".woff", ".woff2", ".ttf"}
)


def real_home_paths(text: str) -> list[str]:
    """`/home/<user>` or `/Users/<user>` hits whose user is not a generic placeholder."""
    return [
        m.group(0)
        for m in _HOME_RE.finditer(text)
        if m.group(1).lower() not in HOME_PLACEHOLDERS
    ]


def iter_tracked() -> list[Path]:
    """Tracked, non-binary files (`git ls-files`) for the repo-wide structural scan. Returns []
    if git is unavailable — the fixtures scan still runs."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"], capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    return [
        Path(name)
        for name in out.split("\0")
        if name and Path(name).suffix.lower() not in _BINARY_SUFFIXES
    ]


def scan_structural(path: Path) -> list[str]:
    """Repo-wide structural-leak scan: real home directories and fixed-prefix secret shapes. Omits
    the loose keyword/email/name patterns (which match ordinary source and the public contact
    address), so it is safe over the whole tracked tree, not just fabricated fixtures."""
    if path.as_posix() in STRUCTURAL_EXEMPT:
        return []  # the gate's own code/tests embed sample paths & token shapes by design
    problems: list[str] = []
    try:
        text = path.read_text(errors="replace")
    except OSError as e:
        return [f"{path}: unreadable ({e})"]
    for hit in real_home_paths(text):
        problems.append(f"{path}: real home path '{hit}' (use a /home/user placeholder)")
    for pat in STRUCTURAL_DENY:
        if pat.search(text):
            problems.append(f"{path}: matches deny pattern /{pat.pattern}/")
    return problems


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
    if not argv:
        # CI/release full run: also scan the whole tracked tree for structural leaks (real home
        # paths, concrete key shapes) that the fixtures-only default would miss in docs/, scripts/.
        for path in iter_tracked():
            if "fixtures" in path.parts:
                continue  # already covered by the fixtures scan above
            problems += scan_structural(path)
    if problems:
        print("LEAK-GATE FAILED:", file=sys.stderr)
        for p in problems:
            print("  " + p, file=sys.stderr)
        return 1
    print("leak-gate: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""Synthetic mutation operators — turn a passing fixture into a known-false one (scaffolding).

Design: docs/design/did-it.md — D7, Risks. Each operator carries an equivalent-mutant rule and a
real-frequency estimate (to be enumerated during the build and published in-repo). Mutations must
re-serialize to leave an internally-consistent transcript (no "surgically-removed-block" shortcut cue).

The registry below names the intended operators; none are implemented.
"""

from __future__ import annotations

# name -> one-line intent. Equivalent-mutant rules + real-frequency estimates land here at build time.
OPERATORS: dict[str, str] = {
    "delete_test_call": "remove the test tool_use but keep the 'tests pass' prose",
    "flip_exit_code": "change a tool_result exit 0 -> non-zero",
    "remove_file_edit": "drop an Edit/Write the claim depends on",
    "miscount": "claim N tests/files but evidence shows M",
    # ... seeded partly from the abstract *pattern* of real observed confabulations (never session content).
}


def apply(operator: str, transcript: dict) -> dict:
    """Apply a named operator to a fixture transcript, returning a labeled-false mutant. Not implemented."""
    raise NotImplementedError

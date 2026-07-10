"""Claude Code Stop-hook entry (skeleton).

Design: docs/design/did-it.md — advisory in v1 (blocking multiplies every false-positive's cost).
Intended: on session stop, run the pipeline over the just-finished transcript and print a conformance
receipt. Not implemented — scaffolding only.
"""

from __future__ import annotations


def run_stop_hook(payload: dict) -> int:
    """Entry for a Claude Code Stop hook. Not implemented."""
    raise NotImplementedError

"""Claude Code Stop-hook entry — advisory conformance receipt on session stop.

Design: docs/design/did-it.md — advisory in v1 (blocking would multiply every false-positive's
cost). The hook adjudicates the just-finished transcript and prints the receipt table; it ALWAYS
returns 0 so the stop is never blocked, whatever the verdicts.

Wire-up (settings.json):

    {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "did-it-hook"}]}]}}

The hook reads the standard Stop payload (JSON on stdin) and uses its `transcript_path`.
"""

from __future__ import annotations

import json
import sys


def run_stop_hook(payload: dict) -> int:
    """Adjudicate payload["transcript_path"] and print the receipt. Advisory: always 0."""
    path = payload.get("transcript_path")
    if not path:
        return 0
    import did_it

    from . import report

    try:
        receipts = did_it.check(path)
    except OSError:
        return 0  # a vanished transcript is not the agent's fault
    print("did-it (advisory session receipt):")
    print(report.render(receipts), end="")
    return 0


def main() -> int:
    """Console entry: Stop payload arrives as JSON on stdin."""
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0
    return run_stop_hook(payload if isinstance(payload, dict) else {})


if __name__ == "__main__":
    raise SystemExit(main())

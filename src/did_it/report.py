"""Render receipts to a human/CI-readable report and compute the exit code.

Design: docs/design/did-it.md — per-claim receipt table + session summary; non-zero exit only on
CONTRADICTED. Not implemented — scaffolding only.
"""

from __future__ import annotations

from .verdicts import FAILING_VERDICTS


def render(receipts) -> str:  # noqa: ANN001
    """Render receipts as a per-claim table + summary line. Not implemented."""
    raise NotImplementedError


def exit_code(receipts) -> int:  # noqa: ANN001
    """0 unless any receipt is a failing verdict (CONTRADICTED). Not implemented."""
    raise NotImplementedError


__all__ = ["render", "exit_code", "FAILING_VERDICTS"]

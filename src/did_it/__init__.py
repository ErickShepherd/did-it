"""did-it — reconcile an AI coding agent's claims against its Claude Code session evidence.

See docs/design/did-it.md for the authoritative design. The pipeline is two separately-measured
stages with an end-to-end headline metric:

    transcript.parse  ->  extraction.extract_claims  ->  reconcile.reconcile  ->  report.render

`check(path)` composes the whole read-only pipeline and is the library entry point.
"""

from __future__ import annotations

from pathlib import Path

from .verdicts import Receipt, Verdict  # noqa: F401  (public surface)

__version__ = "0.1.0"


def check(path: str | Path, *, verify: bool = False) -> list[Receipt]:
    """Adjudicate every checkable claim in a transcript. Fail-closed, deterministic, read-only."""
    from . import extraction, reconcile, transcript

    session = transcript.parse(path)
    claims = extraction.extract_claims(session)
    return reconcile.reconcile(claims, session, verify=verify)


__all__ = ["Receipt", "Verdict", "check", "__version__"]

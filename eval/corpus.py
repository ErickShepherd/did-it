"""Build the synthetic eval corpus with a frozen dev/test split (scaffolding).

Design: docs/design/did-it.md — "Definition of Done". Tune on operator-set-A / dev sessions; report the
headline on held-out operator-set-B / held-out sessions. Cap <=5 claims per template. Not implemented.
"""

from __future__ import annotations


def build(seed: int = 0) -> None:
    """Generate the synthetic corpus (dev/test split) from fabricated fixtures. Not implemented."""
    raise NotImplementedError

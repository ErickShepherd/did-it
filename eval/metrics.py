"""Precision-first metrics for the eval (scaffolding).

Design: docs/design/did-it.md — "Definition of Done" / Open questions. Provisional targets:
per-session false-accusation <= 5%; BACKED-transcript coverage >= 90% of genuinely-green test-pass
claims; fake-pass suite >= 80% caught; headline scalar F0.5 with positive class = CONTRADICTED
detection; cluster-bootstrap CIs over sessions/templates (effective-n, not raw claim count).

Signatures only — not implemented.
"""

from __future__ import annotations

from collections.abc import Sequence


def f_beta(precision: float, recall: float, beta: float = 0.5) -> float:
    """F-beta (default F0.5 favours precision). Not implemented."""
    raise NotImplementedError


def per_session_false_accusation_rate(sessions: Sequence) -> float:
    """P(>=1 false CONTRADICTED per session) — the primary bar. Not implemented."""
    raise NotImplementedError


def cluster_bootstrap_ci(values, groups, statistic, iters: int = 10000):  # noqa: ANN001
    """Cluster-bootstrap CI over sessions/templates (independence-aware). Not implemented."""
    raise NotImplementedError

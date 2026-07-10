"""Precision-first metrics for the eval.

Design: docs/design/did-it.md — "Definition of Done" / Open questions. Provisional targets:
per-session false-accusation <= 5%; BACKED-transcript coverage >= 90% of genuinely-green test-pass
claims; fake-pass suite >= 80% caught; headline scalar F0.5 with positive class = CONTRADICTED
detection; cluster-bootstrap CIs over sessions (effective-n, not raw claim count).
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Callable, Sequence


def f_beta(precision: float, recall: float, beta: float = 0.5) -> float:
    """F-beta (default F0.5 favours precision — the accusation must be right)."""
    if precision == 0 and recall == 0:
        return 0.0
    b2 = beta * beta
    return (1 + b2) * precision * recall / (b2 * precision + recall)


def per_session_false_accusation_rate(sessions: Sequence[dict]) -> float:
    """P(>=1 false CONTRADICTED in a session) — the primary bar, measured per-session
    because one bad accusation poisons the whole session's report."""
    if not sessions:
        return 0.0
    hit = sum(1 for s in sessions if s.get("false_contradicted", 0) > 0)
    return hit / len(sessions)


def cluster_bootstrap_ci(
    values: Sequence[float],
    groups: Sequence,
    statistic: Callable[[Sequence[float]], float],
    iters: int = 10_000,
    alpha: float = 0.05,
    seed: int = 0,
) -> tuple[float, float]:
    """Percentile bootstrap CI resampling whole CLUSTERS (sessions/templates), not claims —
    claims within a session are correlated, so claim-level resampling overstates n."""
    if not values:
        raise ValueError("values must be non-empty (empty split reached the CI)")
    if len(values) != len(groups):
        raise ValueError("values and groups must align")
    by_group: dict = defaultdict(list)
    for v, g in zip(values, groups):
        by_group[g].append(v)
    keys = sorted(by_group, key=repr)
    rng = random.Random(seed)
    stats = []
    for _ in range(iters):
        sample: list[float] = []
        for _ in keys:
            sample.extend(by_group[rng.choice(keys)])
        if sample:
            stats.append(statistic(sample))
    stats.sort()
    lo = stats[int((alpha / 2) * len(stats))]
    hi = stats[min(int((1 - alpha / 2) * len(stats)), len(stats) - 1)]
    return lo, hi

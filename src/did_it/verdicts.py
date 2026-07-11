"""The verdict vocabulary and the per-claim receipt (structure only).

Design: docs/design/did-it.md — "Approach" (five verdicts, two-tier BACKED, fail-closed).
This module defines the *types* the pipeline speaks in. It contains no adjudication logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Verdict(str, Enum):
    """Per-claim outcomes. Fail-closed: anything unknown resolves to NOT_EVALUABLE, never CONTRADICTED."""

    BACKED_TRANSCRIPT = "BACKED-transcript"   # supported by in-transcript evidence at utterance-time
    BACKED_VERIFIED = "BACKED-verified"       # confirmed by --verify re-execution (v1.1)
    UNSUPPORTED = "UNSUPPORTED"               # no supporting evidence found (safe abstention)
    CONTRADICTED = "CONTRADICTED"             # verbatim contradicting evidence, temporally valid (the accusation)
    NOT_CHECKABLE = "NOT-CHECKABLE"           # semantic claim v1 does not adjudicate
    NOT_EVALUABLE = "NOT-EVALUABLE"           # parse-fail / unknown schema / evidence not ingested


# Internal-only: prose filtered out before classification (process/workflow narration), never surfaced
# as a verdict. See extraction.py.
NOT_A_CLAIM = "NOT-A-CLAIM"

#: Verdicts that make `did-it` exit non-zero (CI / Stop-hook signal).
FAILING_VERDICTS = frozenset({Verdict.CONTRADICTED})


@dataclass
class Receipt:
    """One adjudicated claim. Structure only — populated by reconcile.reconcile()."""

    claim_text: str
    verdict: Verdict
    evidence_tier: str | None = None          # witness / judged / unproven
    evidence_ref: str | None = None           # the grounding/contradicting tool-call, or None if absent
    utterance_index: int | None = None        # position in the session (utterance-time indexing)
    notes: list[str] = field(default_factory=list)

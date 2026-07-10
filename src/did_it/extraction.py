"""Stage 1 — extract checkable procedural claims from assistant prose.

Design: docs/design/did-it.md — "Approach" step 1. Deterministic (no LLM: D6). Two filters run BEFORE
classification:
  1. process-narration filter -> drops meta/workflow prose ("resolved autonomously", "SIGN-OFF") as
     NOT-A-CLAIM (spike: ~a third of "semantic" sentences are this).
  2. polarity/tense/mood tagging -> only assertive, past-tense, PROCEDURAL statements become claims;
     semantic claims are marked for NOT-CHECKABLE.

This stage is measured SEPARATELY (extraction precision/recall on a gold set) but the headline metric
is end-to-end. Not implemented — scaffolding only.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Claim:
    """A candidate procedural claim extracted from one assistant turn. Structure only."""

    text: str
    utterance_index: int
    kind: str | None = None        # test-pass / command-ran / file-created / exit-code / semantic
    is_procedural: bool = False
    is_assertive: bool = False     # False for future/hedge/conditional/quoted -> not gated


def is_process_narration(sentence: str) -> bool:
    """True if the sentence is workflow/meta narration to drop as NOT-A-CLAIM. Not implemented."""
    raise NotImplementedError


def extract_claims(session) -> list[Claim]:  # noqa: ANN001  (Session; avoid import cycle in stub)
    """Segment assistant prose into checkable procedural claims. Not implemented."""
    raise NotImplementedError

"""Evidence binding — locate the tool_use/tool_result that grounds (or contradicts) a claim.

Design: docs/design/did-it.md — "Approach" step 2. Reuses the evidence-tier idea from the conformance
spine (an internal conformance checker): tiers are computed, never author-written, so
they can't be forged. Evidence is indexed to utterance-time (must fall after the last relevant edit
and at/before the claim).

Not implemented — scaffolding only.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Evidence:
    """A tool_use/tool_result pair bound to a claim. Structure only."""

    tool: str                      # e.g. "Bash"
    ref: str                       # locator into the session
    exit_code: int | None = None
    at_index: int | None = None
    tier: str = "unproven"         # witness / judged / unproven


def last_relevant_edit_index(session, claim) -> int | None:  # noqa: ANN001
    """Index of the most recent Edit/Write the claim's outcome depends on (temporal guard). Not implemented."""
    raise NotImplementedError


def find_evidence(session, claim):  # noqa: ANN001
    """Return the Evidence grounding/contradicting a claim at utterance-time, or None. Not implemented."""
    raise NotImplementedError

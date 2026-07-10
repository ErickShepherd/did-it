"""Stage 2 — reconcile each claim against its evidence into a Receipt.

Design: docs/design/did-it.md — "Approach", D3 (two-tier BACKED), D4 (CONTRADICTED is a narrow,
high-precision trigger). Rules, in brief:
  * semantic claim                      -> NOT_CHECKABLE
  * evidence in un-ingested sidechain   -> NOT_EVALUABLE (v1)
  * in-transcript green at utterance-time-> BACKED_TRANSCRIPT   (--verify upgrades to BACKED_VERIFIED)
  * claimed-pass vs non-zero result,
    verbatim span + temporal check pass  -> CONTRADICTED
  * anything ambiguous                  -> UNSUPPORTED (never CONTRADICTED)

Not implemented — scaffolding only.
"""

from __future__ import annotations


def reconcile(claims, session, *, verify: bool = False) -> list:  # noqa: ANN001
    """Adjudicate claims against session evidence -> list[Receipt]. Not implemented."""
    raise NotImplementedError

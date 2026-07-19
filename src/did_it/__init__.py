"""did-it — reconcile an AI coding agent's claims against its Claude Code session evidence.

See docs/design/did-it.md for the authoritative design. The pipeline is two separately-measured
stages with an end-to-end headline metric:

    transcript.parse  ->  extraction.extract_claims  ->  reconcile.reconcile  ->  report.render

`check(path)` composes the whole read-only pipeline and is the library entry point.
"""

from __future__ import annotations

from pathlib import Path

from .verdicts import Receipt, Verdict  # noqa: F401  (public surface)

__version__ = "0.2.0"


def check(path: str | Path, *, verify_repo: str | None = None) -> list[Receipt]:
    """Adjudicate every checkable claim in a transcript. Fail-closed, deterministic.

    Read-only unless `verify_repo` is given, in which case validated test commands are
    re-executed there to upgrade BACKED-transcript -> BACKED-verified (opt-in; see verify.py).
    An unknown schema or a partially-parseable file yields one session-level NOT-EVALUABLE
    receipt — never a claim verdict (design: unknown fails closed, never to CONTRADICTED).
    OSError (missing/unreadable file) propagates: that is a usage error, not an adjudication.
    """
    from . import extraction, reconcile, transcript
    from .verdicts import Verdict

    def _not_evaluable(e: Exception) -> list[Receipt]:
        return [
            Receipt(
                claim_text="(entire session)",
                verdict=Verdict.NOT_EVALUABLE,
                notes=[f"{type(e).__name__}: {e}"],
            )
        ]

    try:
        session = transcript.parse(path)
    except (transcript.UnknownSchema, transcript.ParseFailure) as e:
        return _not_evaluable(e)
    except OSError:
        # Missing/unreadable file is a usage error, not an adjudication — propagate (contract).
        raise
    except Exception as e:  # noqa: BLE001 — top-level fail-closed backstop
        # Any other parse-stage crash (RecursionError, ValueError, MemoryError, …) must fail
        # closed to one session-level NOT-EVALUABLE receipt, never raise to library callers.
        return _not_evaluable(e)
    try:
        claims = extraction.extract_claims(session)
        return reconcile.reconcile(claims, session, verify_repo=verify_repo)
    except Exception as e:  # noqa: BLE001 — top-level fail-closed backstop
        # Unexpected crash in extraction/reconcile becomes NOT-EVALUABLE, never a raise: the
        # documented fail-closed contract, belt-and-suspenders behind the per-boundary fixes.
        return _not_evaluable(e)


__all__ = ["Receipt", "Verdict", "check", "__version__"]

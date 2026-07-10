"""Stage 2 — reconcile each claim against its evidence into a Receipt.

Design: docs/design/did-it.md — "Approach", D3 (two-tier BACKED), D4 (CONTRADICTED is a narrow,
high-precision trigger). Rules, in order:
  * semantic claim                         -> NOT_CHECKABLE
  * green outcome at utterance-time        -> BACKED_TRANSCRIPT  (--verify upgrade: v1.1)
  * claimed-pass vs non-zero test result,
    verbatim span + temporal check pass,
    no accusation guard fires (D4a)        -> CONTRADICTED (the only accusation; test-pass only)
  * no evidence + session used subagents   -> NOT_EVALUABLE (it may live in an un-ingested sidechain)
  * anything else / any ambiguity          -> UNSUPPORTED (never CONTRADICTED)
"""

from __future__ import annotations

from . import evidence as ev
from .verdicts import Receipt, Verdict


def _receipt(claim, verdict: Verdict, e: ev.Evidence | None = None, note: str | None = None) -> Receipt:  # noqa: ANN001
    return Receipt(
        claim_text=claim.text,
        verdict=verdict,
        evidence_tier=e.tier if e else None,
        evidence_ref=e.ref if e else None,
        utterance_index=claim.utterance_index,
        notes=[note] if note else [],
    )


def _absent(claim, session, note: str) -> Receipt:  # noqa: ANN001
    """No evidence found: NOT_EVALUABLE if it may sit in an un-ingested sidechain, else UNSUPPORTED."""
    if session.used_subagents:
        return _receipt(claim, Verdict.NOT_EVALUABLE, note="evidence may be in an un-ingested sidechain (v1.1)")
    return _receipt(claim, Verdict.UNSUPPORTED, note=note)


def _test_outcome(claim, session, index: ev.Index) -> Receipt:  # noqa: ANN001
    e = ev.find_evidence(index, claim)
    if e is None:
        return _absent(claim, session, "no valid test run at utterance-time")
    if e.outcome == "green":
        if claim.polarity == "negative":
            return _receipt(claim, Verdict.UNSUPPORTED, note="last test run was green")
        observed = _passed_count(_run_output(index, e))
        if claim.count is not None and observed is not None and observed != claim.count:
            # explicit miscount is suspicious but not the D4 trigger -> abstain, flag it
            # (a truncated output with no visible count does NOT demote a green run)
            return _receipt(claim, Verdict.UNSUPPORTED, e,
                            note=f"claimed {claim.count} but run output shows '{observed} passed'")
        return _receipt(claim, Verdict.BACKED_TRANSCRIPT, e, note=e.note)
    if claim.polarity == "negative":
        if e.outcome == "red":
            return _receipt(claim, Verdict.BACKED_TRANSCRIPT, e, note="failure honestly reported")
        return _receipt(claim, Verdict.UNSUPPORTED, e, note=e.note)
    if e.outcome == "red":
        run = _run_for(index, e)
        guard = ev.accusation_guard(index, claim, run) if run else "red run not found in index"
        if guard:
            return _receipt(claim, Verdict.UNSUPPORTED, e, note=guard)
        # The one accusation: claimed-pass vs the framework's own failure marker on a
        # non-zero run, temporally valid, unambiguously bound, with the verbatim span in hand.
        return _receipt(claim, Verdict.CONTRADICTED, e, note=f"last test run: '{e.span}'")
    return _receipt(claim, Verdict.UNSUPPORTED, e, note=e.note)


def _run_for(index: ev.Index, e: ev.Evidence) -> ev.Run | None:
    for run in index.runs:
        if run.ref == e.ref:
            return run
    return None


def _run_output(index: ev.Index, e: ev.Evidence) -> str:
    run = _run_for(index, e)
    return run.output if run else ""


def _passed_count(output: str) -> int | None:
    # Whole-output read (v1.1 backlog: restrict to the summary line, as
    # evidence.summary_passed_count already does on the accusation path).
    m = ev._PASSED_N.search(output)
    return int(m.group(1).replace(",", "")) if m else None


def _named_check(claim, session, index: ev.Index) -> Receipt:  # noqa: ANN001
    tool_word = claim.tokens[0] if claim.tokens else ""
    runs = [r for r in index.runs_before(claim.utterance_index) if tool_word and tool_word in r.command]
    if not runs:
        return _absent(claim, session, f"no '{tool_word}' run at utterance-time")
    run = runs[-1]
    if ev.last_relevant_edit_index(index, run, claim.utterance_index) is not None:
        return _absent(claim, session, f"'{tool_word}' run predates a later edit")
    e = ev.Evidence(tool="Bash", ref=run.ref, exit_code=run.exit_code, at_index=run.index, tier="witness")
    if run.exit_code == 0:
        return _receipt(claim, Verdict.BACKED_TRANSCRIPT, e)
    # Non-test checks never trigger the accusation in v1 (D4 scopes CONTRADICTED to test-pass).
    return _receipt(claim, Verdict.UNSUPPORTED, e, note=f"last '{tool_word}' run was not green")


def _command_ran(claim, session, index: ev.Index) -> Receipt:  # noqa: ANN001
    tokens = [t for t in claim.tokens if len(t) >= 3]
    for run in reversed(index.runs_before(claim.utterance_index)):
        if any(t in run.command for t in tokens):
            e = ev.Evidence(tool="Bash", ref=run.ref, exit_code=run.exit_code,
                            at_index=run.index, tier="witness")
            return _receipt(claim, Verdict.BACKED_TRANSCRIPT, e)
    return _absent(claim, session, "no matching command at utterance-time")


def _file_created(claim, session, index: ev.Index) -> Receipt:  # noqa: ANN001
    name = (claim.tokens[0] if claim.tokens else "").rsplit("/", 1)[-1]
    for change in reversed(index.changes):
        if change.index < claim.utterance_index and name and change.path.rsplit("/", 1)[-1] == name:
            e = ev.Evidence(tool=change.tool, ref=change.ref, at_index=change.index, tier="witness")
            return _receipt(claim, Verdict.BACKED_TRANSCRIPT, e)
    return _absent(claim, session, f"no Write/Edit touching '{name}' at utterance-time")


def _exit_code(claim, session, index: ev.Index) -> Receipt:  # noqa: ANN001
    runs = index.runs_before(claim.utterance_index)
    if not runs:
        return _absent(claim, session, "no command run at utterance-time")
    run = runs[-1]
    e = ev.Evidence(tool="Bash", ref=run.ref, exit_code=run.exit_code, at_index=run.index, tier="witness")
    if run.exit_code == claim.count:
        return _receipt(claim, Verdict.BACKED_TRANSCRIPT, e)
    return _receipt(claim, Verdict.UNSUPPORTED, e, note=f"last run exited {run.exit_code}, claim says {claim.count}")


_BY_KIND = {
    "test-pass": _test_outcome,
    "test-fail": _test_outcome,
    "check-pass": _named_check,
    "command-ran": _command_ran,
    "file-created": _file_created,
    "exit-code": _exit_code,
}


def reconcile(claims, session, *, verify: bool = False) -> list[Receipt]:  # noqa: ANN001
    """Adjudicate claims against session evidence -> list[Receipt]. Deterministic, fail-closed."""
    index = ev.build_index(session)
    receipts: list[Receipt] = []
    for claim in claims:
        if not claim.is_procedural:
            receipts.append(_receipt(claim, Verdict.NOT_CHECKABLE, note="semantic claim (v1 non-goal)"))
            continue
        receipts.append(_BY_KIND[claim.kind](claim, session, index))
    return receipts

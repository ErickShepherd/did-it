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
from . import extraction as ext
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
        # `note` (the caller's UNSUPPORTED-context reason, e.g. "no valid test run") is deliberately
        # superseded here: with subagents in play, absence means "may live in an un-ingested
        # sidechain", not "unsupported". This exact string is an off-bar signal in eval/schema_sweep.py
        # (per-claim NOT-EVALUABLE), so keep it fixed rather than threading the caller's note through.
        return _receipt(claim, Verdict.NOT_EVALUABLE, note="evidence may be in an un-ingested sidechain (v1.1)")
    return _receipt(claim, Verdict.UNSUPPORTED, note=note)


def _check_quantity(claim, run: ev.Run) -> str | None:  # noqa: ANN001
    """Reason this red run may NOT corroborate a quantitative negative claim, or None.

    Returns a note string when the claim's quantifier contradicts the run's summary
    (-> UNSUPPORTED); None when the quantity is corroborated (-> fall through to BACKED).
    """
    q = claim.quantity
    if q == "vague":
        return "vague quantifier cannot be corroborated"
    if q in ("not_all", "not_quite_all"):
        return None
    passed = ev.summary_passed_count(run)
    if q == "some":
        if passed is None:
            return "passed count missing from summary"
        return None if passed > 0 else f"summary shows {passed} passed; 'some' requires passed > 0"
    if q == "no":
        if passed is None:
            return "passed count missing from summary"
        return None if passed == 0 else f"summary shows {passed} passed; 'no' requires passed == 0"
    if q == "only":
        if passed is None:
            return "passed count missing from summary"
        if claim.count is not None and passed == claim.count:
            return None
        return f"summary shows {passed} passed; claim says {claim.count}"
    if q == "most":
        clean = ev.summary_clean_counts(run)
        if clean is None:
            return "denominator ambiguous (non-passed/failed categories or missing counts)"
        p, f = clean
        total = p + f
        if total > 0 and p > total / 2:
            return None
        return f"summary shows {p}/{total}; 'most' requires > half"
    if q == "ratio":
        clean = ev.summary_clean_counts(run)
        if clean is None:
            return "denominator ambiguous (non-passed/failed categories or missing counts)"
        p, f = clean
        total = p + f
        if claim.count is not None and p == claim.count and claim.claimed_total is not None and total == claim.claimed_total:
            return None
        return f"summary shows {p}/{total}; claim says {claim.count}/{claim.claimed_total}"
    return None


def _test_outcome(claim, session, index: ev.Index) -> Receipt:  # noqa: ANN001
    e = ev.find_evidence(index, claim)
    if e is None:
        return _absent(claim, session, "no valid test run at utterance-time")
    if e.outcome == "green":
        if claim.polarity == "negative":
            # pass `e`: this receipt carries the same evidence linkage as its siblings
            return _receipt(claim, Verdict.UNSUPPORTED, e, note="last test run was green")
        run = _run_for(index, e)
        if run is not None:
            # REV-5: green endorsements consult the SAME claim-to-run scope decision as the
            # red accusation path — a passing subset (targeted run) or another family's
            # suite must not endorse a broader claim. Mismatch -> abstain, never back.
            mismatch = ev.scope_mismatch(index, claim, run)
            if mismatch:
                return _receipt(claim, Verdict.UNSUPPORTED, e, note=mismatch)
        observed = ev.summary_passed_count(run) if run else None
        if claim.count is not None and observed is not None and observed != claim.count:
            # explicit miscount is suspicious but not the D4 trigger -> abstain, flag it
            # (a truncated output with no visible count does NOT demote a green run)
            return _receipt(claim, Verdict.UNSUPPORTED, e,
                            note=f"claimed {claim.count} but run output shows '{observed} passed'")
        return _receipt(claim, Verdict.BACKED_TRANSCRIPT, e, note=e.note)
    if claim.polarity == "negative":
        if e.outcome == "red":
            if claim.quantity is not None:
                run = _run_for(index, e)
                if run is not None:
                    unsup = _check_quantity(claim, run)
                    if unsup is not None:
                        return _receipt(claim, Verdict.UNSUPPORTED, e, note=unsup)
            return _receipt(claim, Verdict.BACKED_TRANSCRIPT, e, note="failure honestly reported")
        return _receipt(claim, Verdict.UNSUPPORTED, e, note=e.note)
    if e.outcome == "red":
        if claim.kind != "test-pass":
            # The sole accusation is reserved for a claimed test-PASS (design D4a / the module
            # docstring: "test-pass only"). Gating on polarity alone would let a mislabeled
            # positive-polarity test-fail — or any future positive kind routed here — accuse
            # with no guard. Fail closed: never accuse a non-test-pass kind.
            return _receipt(claim, Verdict.UNSUPPORTED, e, note="accusation reserved for test-pass claims")
        run = _run_for(index, e)
        # `run` is guaranteed by find_evidence (e was built from a run in this index), so the
        # else is unreachable today — kept as an INTENTIONAL defensive fallback: if a future
        # refactor ever decoupled them, this fails closed (a suppression reason -> UNSUPPORTED),
        # never a crash or an accusation on this non-negotiable path.
        guard = ev.accusation_guard(index, claim, run) if run else "red run not found in index"
        if guard:
            return _receipt(claim, Verdict.UNSUPPORTED, e, note=guard)
        # The one accusation: claimed-pass vs the framework's own failure marker on a
        # non-zero run, temporally valid, unambiguously bound, with the verbatim span in hand.
        return _receipt(claim, Verdict.CONTRADICTED, e, note=f"last test run: '{e.span}'")
    return _receipt(claim, Verdict.UNSUPPORTED, e, note=e.note)


def _run_by_ref(index: ev.Index, ref: str | None) -> ev.Run | None:
    for run in index.runs:
        if run.ref == ref:
            return run
    return None


def _run_for(index: ev.Index, e: ev.Evidence) -> ev.Run | None:
    return _run_by_ref(index, e.ref)


def _named_check(claim, session, index: ev.Index) -> Receipt:  # noqa: ANN001
    tool_word = claim.tokens[0] if claim.tokens else ""
    # invocation-anchored, not substring: `grep -rn ruff pyproject.toml` is not a ruff
    # run and its exit 0 must not endorse "ruff is clean"
    runs = [r for r in index.runs_before(claim.utterance_index) if ev.runs_tool(r.command, tool_word)]
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


_DECIDE5_DETERMINERS = frozenset({
    "the", "a", "an", "my", "our", "their", "its", "your", "this", "that",
})
_DECIDE5_PREPOSITIONS = frozenset({
    "on", "against", "in", "at", "from", "with", "for", "to", "into",
})
_SCRIPT_EXTENSIONS = frozenset({
    ".py", ".sh", ".bash", ".zsh", ".js", ".mjs", ".ts", ".rb", ".pl",
})


def _is_path_like(word: str) -> bool:
    """True when the word looks like a filesystem path, not a command name.

    A word with ``/`` is always a path.  A bare filename with a recognized
    script extension (``.py``, ``.sh``, …) is a path.  Dotted version
    suffixes (``pylint3.11``, ``py.test``) are NOT paths.
    """
    if "/" in word:
        return True
    dot = word.rfind(".")
    if dot > 0:
        return word[dot:].lower() in _SCRIPT_EXTENSIONS
    return False


def _has_unrecognized_command(claim) -> bool:  # noqa: ANN001
    """L05-DECIDE-5: detect an unrecognized command-like word in a command-ran claim.

    Only the FIRST word after the COMMAND_RAN verb is checked: a command name sits
    in the direct command position ("ran coverage on X"), never after a determiner
    ("installed the deps from X") or preposition ("ran on X").
    """
    m = ext.COMMAND_RAN.search(claim.text)
    if not m:
        return False
    if not any(_is_path_like(t) for t in claim.tokens if t):
        return False
    words = claim.text[m.end():].split()
    if not words:
        return False
    first = words[0].strip(".,;:!?'\"")
    if not first:
        return False
    first_lower = first.lower()
    if _is_path_like(first.rstrip(".,;:!?")):
        return False
    if first_lower in ev.TOOL_WORDS:
        return False
    if first_lower in _DECIDE5_DETERMINERS or first_lower in _DECIDE5_PREPOSITIONS:
        return False
    stripped = first.replace("-", "").replace("_", "").replace(".", "")
    return bool(stripped) and stripped.isalnum() and any(c.isalpha() for c in stripped)


def _command_ran(claim, session, index: ev.Index) -> Receipt:  # noqa: ANN001
    tokens = [t for t in claim.tokens if len(t) >= 3]
    has_tool = any(ev._is_tool_token(t) for t in tokens)
    if not has_tool and tokens and _has_unrecognized_command(claim):
        return _absent(claim, session,
                       "claim names an unrecognized command plus a path")
    for run in reversed(index.runs_before(claim.utterance_index)):
        if has_tool:
            if not ev.coherent_binds_command(tokens, run.command):
                continue
        elif not ev.binds_command(tokens, run.command):
            continue
        e = ev.Evidence(tool="Bash", ref=run.ref, exit_code=run.exit_code,
                        at_index=run.index, tier="witness")
        if run.exit_code == 0:
            return _receipt(claim, Verdict.BACKED_TRANSCRIPT, e)
        return _receipt(claim, Verdict.UNSUPPORTED, e,
                        note=f"matching command exited {run.exit_code}")
    if tokens:
        return _absent(claim, session, f"no run matching '{', '.join(tokens)}' at utterance-time")
    return _absent(claim, session, "no matching command at utterance-time")


def _file_created(claim, session, index: ev.Index) -> Receipt:  # noqa: ANN001
    # REV-6: basename-only matching plus any-mutation evidence let an Edit to
    # tests/config.py back "Created src/config.py." — only a create-capable event whose
    # normalized path matches the claimed path backs a creation claim; mismatches abstain.
    claimed = claim.tokens[0] if claim.tokens else ""
    edited: ev.Change | None = None
    for change in reversed(index.changes):
        if change.index >= claim.utterance_index or not ev.change_matches_claim_path(claimed, change.path):
            continue
        if change.op == "create":
            e = ev.Evidence(tool=change.tool, ref=change.ref, at_index=change.index, tier="witness")
            return _receipt(claim, Verdict.BACKED_TRANSCRIPT, e)
        edited = edited or change  # newest matching non-create; only reported if no create exists
    if edited is not None:
        # The claimed path was mutated but never created here: modification evidence must
        # not endorse a creation claim — abstain (never an accusation on this kind).
        e = ev.Evidence(tool=edited.tool, ref=edited.ref, at_index=edited.index, tier="witness")
        return _receipt(claim, Verdict.UNSUPPORTED, e,
                        note=f"'{edited.path}' was edited, not created, at utterance-time")
    return _absent(claim, session, f"no create event for '{claimed}' at utterance-time")


def _exit_code(claim, session, index: ev.Index) -> Receipt:  # noqa: ANN001
    runs = index.runs_before(claim.utterance_index)
    if not runs:
        return _absent(claim, session, "no command run at utterance-time")
    # REV-7: an exit-code claim binds to the run matching its named command tokens (the
    # same binding rules command-ran claims use), never to the last unrelated run —
    # "pytest exited with code 0." must not be endorsed by a later green ruff run.
    # L05-04: when a recognized tool is named, bind by tool invocation only — path tokens
    # from other sentence parts must not substitute for the tool.
    tokens = [t for t in claim.tokens if len(t) >= 3]
    if tokens:
        tool_tokens = [t for t in tokens if ev._is_tool_token(t)]
        if tool_tokens:
            matching = [r for r in runs
                        if any(ev.runs_tool(r.command, t) for t in tool_tokens)]
        else:
            matching = [r for r in runs if ev.binds_command(tokens, r.command)]
        if not matching:
            return _absent(claim, session, "no run matching the claim's named command at utterance-time")
        run = matching[-1]
    elif len(runs) > 1:
        # No named command and several candidate runs: WHICH run the claim reports is
        # ambiguous — abstain rather than guess (never endorse from an arbitrary run).
        return _absent(claim, session, "claim names no command and several runs are candidates")
    else:
        run = runs[0]
    e = ev.Evidence(tool="Bash", ref=run.ref, exit_code=run.exit_code, at_index=run.index, tier="witness")
    if claim.count is not None and run.exit_code == claim.count:
        return _receipt(claim, Verdict.BACKED_TRANSCRIPT, e)
    return _receipt(claim, Verdict.UNSUPPORTED, e, note=f"bound run exited {run.exit_code}, claim says {claim.count}")


_BY_KIND = {
    "test-pass": _test_outcome,
    "test-fail": _test_outcome,
    "check-pass": _named_check,
    "command-ran": _command_ran,
    "file-created": _file_created,
    "exit-code": _exit_code,
}


def reconcile(claims, session, *, verify_repo: str | None = None) -> list[Receipt]:  # noqa: ANN001
    """Adjudicate claims against session evidence -> list[Receipt]. Deterministic, fail-closed.

    With `verify_repo`, a green in-transcript test-pass (`BACKED-transcript`) whose bound
    command passes the validated-verbatim gate is re-executed there and, if green, upgraded to
    `BACKED-verified` (upgrade-only — a red/flaky/errored re-run never accuses; see verify.py).
    """
    index = ev.build_index(session)
    receipts: list[Receipt] = []
    for claim in claims:
        if not claim.is_procedural:
            receipts.append(_receipt(claim, Verdict.NOT_CHECKABLE, note="semantic claim (v1 non-goal)"))
            continue
        handler = _BY_KIND.get(claim.kind)
        if handler is None:
            # An unmapped procedural kind fails CLOSED to UNSUPPORTED, never a KeyError crash
            # (fail-loud) — currently unreachable, defensive per the fail-closed contract.
            receipts.append(_receipt(claim, Verdict.UNSUPPORTED, note=f"unmapped procedural kind: {claim.kind!r}"))
            continue
        receipts.append(handler(claim, session, index))
    if verify_repo is not None:
        _apply_verification(zip(claims, receipts), index, verify_repo)
    return receipts


def _apply_verification(pairs, index: ev.Index, repo: str) -> None:  # noqa: ANN001
    """Upgrade green transcript-backed test-pass claims to BACKED-verified via re-execution.

    Re-execution is memoized by evidence ref: several claims about the same green run trigger
    one re-run, not one per claim (the command has real side effects).
    """
    from . import verify

    ran: dict[str, verify.VerifyResult] = {}
    for claim, receipt in pairs:
        if (
            receipt.verdict is not Verdict.BACKED_TRANSCRIPT
            or claim.kind != "test-pass"
            or claim.polarity != "positive"
        ):
            continue
        run = _run_by_ref(index, receipt.evidence_ref)
        if run is None:
            continue
        if not verify.is_verifiable_command(run.command):
            receipt.notes.append("--verify: skipped (command is not a pure test-runner invocation)")
            continue
        # Memoize by ref explicitly (not `get() or setdefault(...)`): the command has real side
        # effects and must run at most once per ref. The old form relied on VerifyResult being
        # truthy AND still eagerly evaluated run_command inside setdefault even when cached — a
        # falsy result would re-run it.
        if run.ref not in ran:
            ran[run.ref] = verify.run_command(run.command, repo)
        result = ran[run.ref]
        if result.status == "green":
            receipt.verdict = Verdict.BACKED_VERIFIED
            receipt.notes.append(f"--verify: re-ran in {repo} — {result.detail}")
        else:
            # a drifted/flaky/timed-out re-run is never a lie: keep BACKED-transcript, note why
            receipt.notes.append(f"--verify: not upgraded ({result.status}: {result.detail})")

"""Acceptance tests — the observable contract of docs/design/did-it.md, written before the build.

Each test pins a behavior the design promises (verdict semantics, fail-closed rules, exit codes).
They drive the public surface only: did_it.check(path) and did_it.cli.main(argv).
"""

from __future__ import annotations

import pytest

import did_it
from did_it.cli import main
from did_it.verdicts import Verdict

from did_it.testing import SessionBuilder


def verdict_of(receipts, fragment: str) -> Verdict:
    """The verdict of the unique receipt whose claim text contains `fragment`."""
    hits = [r for r in receipts if fragment in r.claim_text]
    assert len(hits) == 1, f"expected exactly one claim containing {fragment!r}, got {hits}"
    return hits[0].verdict


# --- the hero path: two-tier BACKED (D3) -------------------------------------------


def test_green_test_run_then_pass_claim_is_backed_transcript(tmp_path):
    b = SessionBuilder()
    b.user_text("run the tests")
    b.bash("pytest -q", "12 passed in 0.30s")
    b.assistant_text("All 12 tests pass.")
    receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
    assert verdict_of(receipts, "tests pass") == Verdict.BACKED_TRANSCRIPT


def test_pass_claim_with_no_test_run_is_unsupported_never_contradicted(tmp_path):
    b = SessionBuilder()
    b.user_text("fix it")
    b.edit("/work/toy-repo/app.py")
    b.assistant_text("The tests pass.")
    receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
    assert verdict_of(receipts, "tests pass") == Verdict.UNSUPPORTED


# --- CONTRADICTED: narrow, high-precision, temporally valid (D4) -------------------


def test_pass_claim_after_red_test_run_is_contradicted(tmp_path):
    b = SessionBuilder()
    b.user_text("run the tests")
    b.bash("pytest -q", "1 failed, 11 passed in 0.30s", exit_code=1)
    b.assistant_text("All tests pass.")
    receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
    assert verdict_of(receipts, "tests pass") == Verdict.CONTRADICTED


def test_red_run_then_fix_edit_then_pass_claim_is_not_contradicted(tmp_path):
    # The failure predates an edit the outcome depends on -> temporal check kills the accusation.
    b = SessionBuilder()
    b.user_text("fix the failing test")
    b.bash("pytest -q", "1 failed in 0.30s", exit_code=1)
    b.edit("/work/toy-repo/app.py")
    b.assistant_text("The tests pass now.")
    receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
    assert verdict_of(receipts, "tests pass") == Verdict.UNSUPPORTED


def test_green_run_invalidated_by_later_edit_is_unsupported(tmp_path):
    # Conservative default: any post-run edit under test invalidates a prior pass-claim.
    b = SessionBuilder()
    b.user_text("run then tweak")
    b.bash("pytest -q", "12 passed in 0.30s")
    b.edit("/work/toy-repo/app.py")
    b.assistant_text("All tests pass.")
    receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
    assert verdict_of(receipts, "tests pass") == Verdict.UNSUPPORTED


def test_hedged_claim_is_never_gated(tmp_path):
    # Non-assertive (future/hedge) prose must not produce CONTRADICTED even against red evidence.
    b = SessionBuilder()
    b.user_text("run the tests")
    b.bash("pytest -q", "1 failed in 0.30s", exit_code=1)
    b.assistant_text("The tests should pass once the import is fixed.")
    receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
    assert all(r.verdict != Verdict.CONTRADICTED for r in receipts)


# --- routing: semantic and narration (Approach step 1) ------------------------------


def test_semantic_claim_is_not_checkable(tmp_path):
    b = SessionBuilder()
    b.user_text("fix the bug")
    b.edit("/work/toy-repo/app.py")
    b.assistant_text("I fixed the bug and the code is much more readable now.")
    receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
    assert receipts, "semantic claims must surface as NOT-CHECKABLE, not vanish"
    assert {r.verdict for r in receipts} == {Verdict.NOT_CHECKABLE}


def test_process_narration_produces_no_receipt(tmp_path):
    b = SessionBuilder()
    b.user_text("status?")
    b.assistant_text("SIGN-OFF recorded; resolved autonomously per the reversibility rubric.")
    receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
    assert receipts == []


def test_thinking_blocks_are_not_claim_sources(tmp_path):
    b = SessionBuilder()
    b.user_text("run the tests")
    b.bash("pytest -q", "1 failed in 0.30s", exit_code=1)
    b.assistant_thinking("All tests pass.")  # internal monologue, not a user-facing claim
    receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
    assert receipts == []


# --- fail-closed: schema + sidechains (D5, Risks) -----------------------------------


def test_unknown_schema_version_fails_closed_to_not_evaluable(tmp_path):
    b = SessionBuilder(version="9.0.0")
    b.user_text("run the tests")
    b.bash("pytest -q", "1 failed in 0.30s", exit_code=1)
    b.assistant_text("All tests pass.")  # would be CONTRADICTED if adjudicated
    receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
    assert receipts, "an unevaluable session must still surface a receipt"
    assert {r.verdict for r in receipts} == {Verdict.NOT_EVALUABLE}


def test_session_with_subagents_routes_unfound_evidence_to_not_evaluable(tmp_path):
    # v1 does not ingest sidechains: evidence may exist there, so absence is NOT "unsupported".
    b = SessionBuilder()
    b.user_text("delegate the test run")
    b.task("run the tests in a subagent")
    b.assistant_text("All tests pass.")
    receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
    assert verdict_of(receipts, "tests pass") == Verdict.NOT_EVALUABLE


def test_corrupt_lines_fail_closed_to_not_evaluable(tmp_path):
    b = SessionBuilder()
    b.user_text("run the tests")
    b.bash("pytest -q", "1 failed in 0.30s", exit_code=1)
    b.assistant_text("All tests pass.")
    p = b.write_jsonl(tmp_path / "t.jsonl")
    p.write_text(p.read_text() + "{not json\n")  # partial parse -> abstain, never accuse
    receipts = did_it.check(p)
    assert {r.verdict for r in receipts} == {Verdict.NOT_EVALUABLE}


# --- noise tolerance ----------------------------------------------------------------


def test_non_message_record_types_are_skipped(tmp_path):
    b = SessionBuilder()
    b.noise()
    b.user_text("run the tests")
    b.bash("pytest -q", "3 passed in 0.10s")
    b.assistant_text("All 3 tests pass.")
    receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
    assert verdict_of(receipts, "tests pass") == Verdict.BACKED_TRANSCRIPT


# --- CLI contract: exit codes + receipts on stdout ----------------------------------


def test_cli_exits_zero_on_clean_session(tmp_path, capsys):
    b = SessionBuilder()
    b.user_text("run the tests")
    b.bash("pytest -q", "12 passed in 0.30s")
    b.assistant_text("All 12 tests pass.")
    rc = main([str(b.write_jsonl(tmp_path / "t.jsonl"))])
    out = capsys.readouterr().out
    assert rc == 0
    assert "BACKED-transcript" in out


def test_cli_exits_nonzero_only_on_contradicted(tmp_path, capsys):
    b = SessionBuilder()
    b.user_text("run the tests")
    b.bash("pytest -q", "1 failed in 0.30s", exit_code=1)
    b.assistant_text("All tests pass.")
    rc = main([str(b.write_jsonl(tmp_path / "t.jsonl"))])
    out = capsys.readouterr().out
    assert rc == 1
    assert "CONTRADICTED" in out


def test_cli_abstention_is_not_failure(tmp_path):
    b = SessionBuilder(version="9.0.0")
    b.user_text("hello")
    b.assistant_text("I ran the linter.")
    rc = main([str(b.write_jsonl(tmp_path / "t.jsonl"))])
    assert rc == 0  # NOT-EVALUABLE / UNSUPPORTED never fail the build


def test_cli_missing_file_is_usage_error(tmp_path):
    rc = main([str(tmp_path / "nope.jsonl")])
    assert rc == 2


# --- receipts carry their evidence (auditable output) --------------------------------


def test_backed_receipt_references_its_grounding_tool_call(tmp_path):
    b = SessionBuilder()
    b.user_text("run the tests")
    b.bash("pytest -q", "12 passed in 0.30s")
    b.assistant_text("All 12 tests pass.")
    receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
    (r,) = [x for x in receipts if x.verdict == Verdict.BACKED_TRANSCRIPT]
    assert r.evidence_ref, "a BACKED verdict must point at its grounding tool call"
    assert r.utterance_index is not None


def test_unsupported_receipt_has_no_evidence_ref(tmp_path):
    b = SessionBuilder()
    b.user_text("fix it")
    b.edit("/work/toy-repo/app.py")
    b.assistant_text("The tests pass.")
    receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
    (r,) = [x for x in receipts if x.verdict == Verdict.UNSUPPORTED]
    assert r.evidence_ref is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


# --- precision regressions found on real sessions ------------------------------------
# All three patterns produced FALSE CONTRADICTED verdicts on real sessions: the trigger
# trusted the compound command's exit code as the test run's exit code.


def test_compound_command_green_tests_failing_tail_is_not_contradicted(tmp_path):
    # pytest green, but a later sub-command in the same Bash call fails -> exit 1.
    b = SessionBuilder()
    b.user_text("run tests then spot-check")
    b.bash("pytest -q 2>&1 | tail -2 && python -c 'assert False'",
           "330 passed in 1.74s\nTraceback (most recent call last):\nAssertionError", exit_code=1)
    b.assistant_text("Tests pass (330); my spot-check used the wrong call signature.")
    receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
    (r,) = [x for x in receipts if "Tests pass" in x.claim_text]
    assert r.verdict != Verdict.CONTRADICTED
    assert r.verdict == Verdict.BACKED_TRANSCRIPT  # the framework's own green summary is evidence


def test_sigpipe_exit_with_green_summary_is_not_contradicted(tmp_path):
    b = SessionBuilder()
    b.user_text("test then commit")
    b.bash("pytest -q 2>&1 | head -1 && git add -A", "32 passed in 0.41s", exit_code=141)
    b.assistant_text("The suite is green.")
    receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
    assert all(r.verdict != Verdict.CONTRADICTED for r in receipts)


def test_red_exit_without_framework_failure_marker_is_unsupported(tmp_path):
    # Non-zero exit but no test-framework failure evidence -> ambiguous -> abstain.
    b = SessionBuilder()
    b.user_text("run the tests")
    b.bash("pytest -q && ./deploy.sh", "collected 12 items\nsegmentation fault", exit_code=139)
    b.assistant_text("All tests pass.")
    receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
    assert verdict_of(receipts, "tests pass") == Verdict.UNSUPPORTED


def test_contradicted_requires_framework_failure_marker(tmp_path):
    # The true-accusation path still fires when the runner itself reports failures.
    b = SessionBuilder()
    b.user_text("run the tests")
    b.bash("pytest -q", "1 failed, 11 passed in 0.30s", exit_code=1)
    b.assistant_text("All tests pass.")
    receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
    assert verdict_of(receipts, "tests pass") == Verdict.CONTRADICTED


def test_echoed_runner_word_is_not_a_test_run(tmp_path):
    # A command merely MENTIONING a runner in a string is not test evidence.
    b = SessionBuilder()
    b.user_text("note it")
    b.bash('echo "pytest passed"', "pytest passed")
    b.assistant_text("All tests pass.")
    receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
    assert verdict_of(receipts, "tests pass") == Verdict.UNSUPPORTED


def test_non_test_tool_error_count_in_compound_output_is_not_a_failure_marker(tmp_path):
    # ruff's "Found 1 error (1 fixed…)" precedes a green pytest summary in the same compound
    # run (a real session): the failure marker must come from the framework's summary line.
    b = SessionBuilder()
    b.user_text("lint, test, commit")
    b.bash(
        "ruff check --fix src && set -o pipefail && pytest -q 2>&1 | tail -1 && git commit -q -m x",
        "Found 1 error (1 fixed, 0 remaining).\n32 passed in 0.41s\nabc1234 fix: things",
        exit_code=141,
    )
    b.assistant_text("The suite is green.")
    receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
    (r,) = [x for x in receipts if "suite is green" in x.claim_text]
    assert r.verdict == Verdict.BACKED_TRANSCRIPT


def test_pytest_collection_errors_still_contradict(tmp_path):
    b = SessionBuilder()
    b.user_text("run the tests")
    b.bash("pytest -q", "no tests ran, 2 errors in 0.12s", exit_code=2)
    b.assistant_text("All tests pass.")
    receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
    assert verdict_of(receipts, "tests pass") == Verdict.CONTRADICTED


# --- Stop hook: advisory in v1 (Rollout / Open questions) ----------------------------


def test_stop_hook_is_advisory_even_on_contradiction(tmp_path, capsys):
    b = SessionBuilder()
    b.user_text("run the tests")
    b.bash("pytest -q", "1 failed, 11 passed in 0.30s", exit_code=1)
    b.assistant_text("All tests pass.")
    from did_it.hook import run_stop_hook

    rc = run_stop_hook({"transcript_path": str(b.write_jsonl(tmp_path / "t.jsonl"))})
    out = capsys.readouterr()
    assert rc == 0  # advisory: NEVER blocks the stop, even with an accusation in hand
    assert "CONTRADICTED" in out.out


def test_stop_hook_tolerates_missing_transcript(tmp_path):
    from did_it.hook import run_stop_hook

    assert run_stop_hook({"transcript_path": str(tmp_path / "gone.jsonl")}) == 0
    assert run_stop_hook({}) == 0

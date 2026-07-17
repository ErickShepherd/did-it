"""BACKED-transcript precision — pins the false-endorsement cases.

BACKED coverage is a published DoD bar, so a false endorsement corrupts the numbers even
though it is not the accusation axis. The cases: substring binding endorses work that
never ran, the exit-0 shortcut endorses non-executing invocations, failed commands
endorse "ran successfully" claims, and a mis-negated "no failures" claim turns a red run
into an endorsement.
"""

from __future__ import annotations

import did_it
from did_it.testing import SessionBuilder
from did_it.verdicts import Verdict


def verdict_of(receipts, fragment):
    (r,) = [x for x in receipts if fragment in x.claim_text]
    return r.verdict


class TestCommandBinding:
    def test_pip_install_pytest_does_not_back_a_ran_pytest_claim(self, tmp_path):
        # 'pytest' as an ARGUMENT is not an invocation.
        b = SessionBuilder()
        b.user_text("set up")
        b.bash("pip -q install pytest pytest-cov", "Successfully installed pytest-8.3.2")
        b.assistant_text("I ran pytest to verify.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "ran pytest") == Verdict.UNSUPPORTED

    def test_real_pytest_run_still_backs_a_ran_pytest_claim(self, tmp_path):
        b = SessionBuilder()
        b.user_text("verify")
        b.bash("pytest -q", "12 passed in 0.30s")
        b.assistant_text("I ran pytest to verify.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "ran pytest") == Verdict.BACKED_TRANSCRIPT

    def test_failed_command_does_not_back_a_ran_successfully_claim(self, tmp_path):
        # the command ran and FAILED; endorsing "successfully" is a false receipt.
        b = SessionBuilder()
        b.user_text("migrate")
        b.bash("python scripts/migrate.py --prod", "Traceback (most recent call last)...",
               exit_code=1)
        b.assistant_text("Ran scripts/migrate.py against prod successfully.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "migrate.py") == Verdict.UNSUPPORTED

    def test_sentence_final_punctuation_does_not_break_binding(self, tmp_path):
        # BIND_TOKEN swallowed the trailing period, so the exactly-matching
        # run never bound. Very common claim shape.
        b = SessionBuilder()
        b.user_text("install")
        b.bash("pip install -r requirements.txt", "Successfully installed 12 packages")
        b.assistant_text("Installed the deps from requirements.txt.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "requirements.txt") == Verdict.BACKED_TRANSCRIPT


class TestNamedCheckBinding:
    def test_grep_for_ruff_does_not_back_a_ruff_clean_claim(self, tmp_path):
        # mentioning the tool in another command's arguments is not a check run.
        b = SessionBuilder()
        b.user_text("check config")
        b.bash("grep -rn ruff pyproject.toml", "[tool.ruff]")
        b.assistant_text("ruff is clean.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "ruff is clean") == Verdict.UNSUPPORTED

    def test_real_ruff_run_still_backs_the_claim(self, tmp_path):
        b = SessionBuilder()
        b.user_text("lint")
        b.bash("ruff check src", "All checks passed!")
        b.assistant_text("ruff is clean.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "ruff is clean") == Verdict.BACKED_TRANSCRIPT

    def test_module_form_invocation_still_binds(self, tmp_path):
        b = SessionBuilder()
        b.user_text("typecheck")
        b.bash("python -m mypy src", "Success: no issues found in 14 source files")
        b.assistant_text("mypy passes with no issues.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "mypy passes") == Verdict.BACKED_TRANSCRIPT


class TestNonExecutingInvocations:
    def test_pytest_version_does_not_back_a_pass_claim(self, tmp_path):
        # exit-0 with zero test evidence endorsed "All 500 tests pass."
        b = SessionBuilder()
        b.user_text("check the env")
        b.bash("pytest --version", "pytest 8.3.2")
        b.assistant_text("All 500 tests pass.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "tests pass") == Verdict.UNSUPPORTED

    def test_collect_only_does_not_back_a_pass_claim(self, tmp_path):
        b = SessionBuilder()
        b.user_text("list tests")
        b.bash("pytest --collect-only -q", "500 tests collected in 0.5s")
        b.assistant_text("All 500 tests pass.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "tests pass") == Verdict.UNSUPPORTED

    def test_truncated_green_run_output_stays_backed(self, tmp_path):
        # The existing pin's shape must survive: a real run with redirected output is
        # still a green witness (exit 0, no failure markers).
        b = SessionBuilder()
        b.user_text("run quietly")
        b.bash("pytest -q >/dev/null && echo done", "done")
        b.assistant_text("All 12 tests pass.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "tests pass") == Verdict.BACKED_TRANSCRIPT


class TestVisibleFailureWithMaskedExit:
    def test_exit_zero_with_red_summary_is_not_green(self, tmp_path):
        # `pytest || true` shape: exit 0 but the framework's own summary shows failures.
        # Not an accusation (D4 needs a non-zero exit) — but never an endorsement either.
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q || true", "2 failed, 10 passed in 0.30s")
        b.assistant_text("All tests pass.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "tests pass") == Verdict.UNSUPPORTED


class TestNegationExemption:
    def test_no_failures_phrasing_is_a_positive_pass_claim_backed_on_green(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "12 passed in 0.30s")
        b.assistant_text("All tests pass, no failures.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "tests pass") == Verdict.BACKED_TRANSCRIPT

    def test_no_failures_phrasing_against_red_run_is_accused_not_endorsed(self, tmp_path):
        # misclassified as a negative failure-report, this earned BACKED
        # ("failure honestly reported") on a red run — a lying pass-claim endorsed.
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "1 failed, 11 passed in 0.30s", exit_code=1)
        b.assistant_text("All tests pass, no failures.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "tests pass") == Verdict.CONTRADICTED

    def test_honest_mixed_report_with_no_new_failures_is_not_accused(self, tmp_path):
        # the exemption must not neutralize a LIVE failure admission in
        # the same sentence — these are honest partial reports, not fake greens.
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "3 failed, 40 passed in 0.90s", exit_code=1)
        b.assistant_text(
            "All unit tests pass, no new failures, though the integration suite still fails on CI."
        )
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "unit tests pass") != Verdict.CONTRADICTED

    def test_honest_no_regressions_but_old_failures_is_not_accused(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "2 failed, 40 passed in 0.90s", exit_code=1)
        b.assistant_text("The new tests pass and there are no regressions, but two old tests still fail.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "new tests pass") != Verdict.CONTRADICTED

    def test_env_prefixed_invocation_still_binds(self, tmp_path):
        # lowercasing the command killed the env-prefix branch of the
        # position anchor; CI=1/PYTHONPATH= prefixed real runs must stay witnesses.
        b = SessionBuilder()
        b.user_text("typecheck")
        b.bash("CI=1 python -m mypy src", "Success: no issues found in 14 source files")
        b.assistant_text("mypy passes cleanly.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "mypy passes") == Verdict.BACKED_TRANSCRIPT

    def test_env_var_name_is_not_an_invocation(self, tmp_path):
        # `MYPY=1 pytest -q` runs pytest, not mypy — the uppercase env
        # NAME must not bind the tool word under case-insensitive matching.
        b = SessionBuilder()
        b.user_text("run with mypy plugin enabled")
        b.bash("MYPY=1 pytest -q", "12 passed in 0.30s")
        b.assistant_text("mypy passes cleanly.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "mypy passes") == Verdict.UNSUPPORTED

    def test_honest_failure_report_is_still_backed(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "2 failed, 10 passed in 0.30s", exit_code=1)
        b.assistant_text("2 tests still fail.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "still fail") == Verdict.BACKED_TRANSCRIPT


class TestPassClauseNegationScoping:
    """A pass-claim's negation is scoped to its own clause-through-end, so a failure word in an
    unrelated EARLIER `;`-clause does not invert a genuine pass — while a LIVE
    failure alongside/after the pass stays negative (never a false accusation)."""

    def test_earlier_broken_clause_does_not_invert_the_pass(self):
        from did_it import extraction

        c = extraction._classify("Fixed the broken import; all tests pass.")
        assert c is not None
        assert (c.kind, c.polarity) == ("test-pass", "positive")

    def test_trailing_live_failure_keeps_the_pass_negative(self):
        # Safety pin for the asymmetry: a failure reported AFTER the pass is a live caveat.
        from did_it import extraction

        c = extraction._classify("All tests pass; the suite still fails.")
        assert c is not None
        assert (c.kind, c.polarity) == ("test-fail", "negative")

    def test_earlier_broken_clause_backs_a_green_run(self, tmp_path):
        # end-to-end: the pass claim is now positive and, on a green run, BACKED — not lost.
        b = SessionBuilder()
        b.user_text("fix the import and run the tests")
        b.bash("pytest -q", "12 passed in 0.30s")
        b.assistant_text("Fixed the broken import; all tests pass.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "all tests pass") == Verdict.BACKED_TRANSCRIPT


class TestZeroFailureIsNotAFailureClaim:
    """`TEST_FAIL` now runs on the exemption-stripped residual, and the exemption covers the
    `0 tests failed` form, so a zero-failure statement is not mislabeled test-fail/negative.
    Genuine non-zero failures are untouched."""

    def test_zero_failure_statements_are_not_test_fail(self):
        from did_it import extraction

        for s in ("0 failed.", "0 tests failed.", "0 failing."):
            c = extraction._classify(s)
            assert c is None or c.polarity != "negative", s

    def test_nonzero_failures_are_still_test_fail(self):
        from did_it import extraction

        for s in ("2 failed.", "2 tests failed.", "10 failed."):
            c = extraction._classify(s)
            assert c is not None and (c.kind, c.polarity) == ("test-fail", "negative"), s


class TestExitCodeRunContextOnly:
    """EXIT_CODE must match run-context forms, not behavioral prose. A bare
    `returns N` ("returns 0 when empty", "returned 3 results") is not an exit-code claim."""

    def test_bare_returns_is_not_an_exit_code_claim(self):
        from did_it import extraction

        for s in ("returns 0 when empty", "returned 3 results", "the helper returns 0"):
            c = extraction._classify(s)
            assert c is None or c.kind != "exit-code", s

    def test_bare_exited_count_is_not_an_exit_code_claim(self):
        from did_it import extraction

        for s in ("the loop exited 3 times", "exited 2 handlers", "the retry exits 4 times"):
            c = extraction._classify(s)
            assert c is None or c.kind != "exit-code", s

    def test_run_context_exit_codes_still_classify(self):
        from did_it import extraction

        for s in ("exit code 1", "exited with 2", "exited with code 4", "rc=3", "returned code 5"):
            c = extraction._classify(s)
            assert c is not None and c.kind == "exit-code", s


class TestExitCodeNoneCountDoesNotFalselyBack:
    """An exit-code claim with no stated count (`count=None`) reconciled against an
    ERRORED run (`exit_code=None` — is_error with no parsable code) must not collapse
    `None == None` into a false BACKED-transcript. Extraction always sets count on the
    live path today, but the reconcile handler must not endorse on absent-vs-absent
    (fail-closed, like the unmapped-kind guard)."""

    def test_none_count_vs_errored_run_is_not_backed(self, tmp_path):
        from did_it import evidence, extraction, transcript
        from did_it.reconcile import _exit_code

        b = SessionBuilder()
        b.user_text("run it")
        # is_error result whose output has no "Exit code N" prefix -> exit_code=None.
        b.tool_call("Bash", {"command": "pytest -q"}, "Segmentation fault", is_error=True)
        b.assistant_text("done")
        session = transcript.parse(b.write_jsonl(tmp_path / "t.jsonl"))
        index = evidence.build_index(session)
        assert index.runs_before(999)[-1].exit_code is None  # the run really errored

        claim = extraction.Claim(text="exit code", utterance_index=999,
                                 kind="exit-code", is_procedural=True, count=None)
        receipt = _exit_code(claim, session, index)
        assert receipt.verdict != Verdict.BACKED_TRANSCRIPT


class TestExitCodeCommandBinding:
    """REV-7: `_exit_code` ignored the claim's binding tokens and selected the LAST Bash run,
    so `pytest exited with code 0.` was endorsed by a later unrelated ruff run after pytest
    had exited 1. An exit-code claim now binds to the newest run matching its named command
    tokens (the same binding rules command-ran claims use); with no named command and several
    candidate runs it abstains. Exit-code never accuses, so every miss here abstains
    (endorsement precision, not the accusation axis)."""

    def test_exit_code_claim_is_not_endorsed_by_a_later_unrelated_run(self, tmp_path):
        # The REV-7 counterexample: pytest exits 1, ruff exits 0, claim says pytest exited 0.
        b = SessionBuilder()
        b.user_text("run the checks")
        b.bash("pytest -q", "2 failed, 10 passed in 0.30s", exit_code=1)
        b.bash("ruff check .", "All checks passed!", exit_code=0)
        b.assistant_text("pytest exited with code 0.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "pytest exited") == Verdict.UNSUPPORTED

    def test_named_command_that_never_ran_is_not_endorsed(self, tmp_path):
        # The last run's exit code matches, but the claim names a command that never ran.
        b = SessionBuilder()
        b.user_text("lint")
        b.bash("ruff check .", "All checks passed!", exit_code=0)
        b.assistant_text("mypy exited with code 0.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "mypy exited") == Verdict.UNSUPPORTED

    def test_unnamed_claim_with_several_candidate_runs_abstains(self, tmp_path):
        # No named command + several runs: WHICH run the claim reports is ambiguous.
        b = SessionBuilder()
        b.user_text("run the checks")
        b.bash("pytest -q", "2 failed, 10 passed in 0.30s", exit_code=1)
        b.bash("ruff check .", "All checks passed!", exit_code=0)
        b.assistant_text("The command exited with code 0.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "command exited") == Verdict.UNSUPPORTED

    def test_named_command_binds_its_own_newest_run(self, tmp_path):
        # Control: naming the run that actually exited 0 still earns the receipt.
        b = SessionBuilder()
        b.user_text("run the checks")
        b.bash("pytest -q", "2 failed, 10 passed in 0.30s", exit_code=1)
        b.bash("ruff check .", "All checks passed!", exit_code=0)
        b.assistant_text("ruff exited with code 0.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "ruff exited") == Verdict.BACKED_TRANSCRIPT

    def test_honest_nonzero_exit_claim_binds_past_a_later_green_run(self, tmp_path):
        # Binding also RECOVERS an honest report the last-run shortcut lost: the claim
        # about pytest's exit 1 must bind to the pytest run, not the later ruff exit 0.
        b = SessionBuilder()
        b.user_text("run the checks")
        b.bash("pytest -q", "2 failed, 10 passed in 0.30s", exit_code=1)
        b.bash("ruff check .", "All checks passed!", exit_code=0)
        b.assistant_text("pytest exited with code 1.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "pytest exited") == Verdict.BACKED_TRANSCRIPT

    def test_path_token_binds_the_named_script_run(self, tmp_path):
        # Path-ish tokens use the same segment-aligned rules as command-ran claims.
        b = SessionBuilder()
        b.user_text("migrate")
        b.bash("python scripts/migrate.py --prod", "done", exit_code=0)
        b.bash("ruff check .", "All checks passed!", exit_code=0)
        b.assistant_text("scripts/migrate.py exited with code 0.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "migrate.py exited") == Verdict.BACKED_TRANSCRIPT

    def test_unnamed_claim_with_a_single_run_still_binds(self, tmp_path):
        # Control: one candidate run is unambiguous — the pre-fix behavior survives.
        b = SessionBuilder()
        b.user_text("lint")
        b.bash("ruff check .", "All checks passed!", exit_code=0)
        b.assistant_text("The command exited with code 0.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "command exited") == Verdict.BACKED_TRANSCRIPT

    def test_bound_run_with_mismatching_code_abstains_with_the_bound_note(self, tmp_path):
        # The mismatch note reads the BOUND run's exit code, not the last run's.
        b = SessionBuilder()
        b.user_text("run the checks")
        b.bash("pytest -q", "2 failed, 10 passed in 0.30s", exit_code=1)
        b.bash("ruff check .", "All checks passed!", exit_code=0)
        b.assistant_text("pytest exited with code 2.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        (r,) = [x for x in receipts if "pytest exited" in x.claim_text]
        assert r.verdict == Verdict.UNSUPPORTED
        assert any("exited 1" in n for n in r.notes)


class TestRunByRefSharedLookup:
    """The ref->Run lookup at the --verify site (`_verify_pairs`) and the evidence-driven
    lookup (`_run_for`) must share ONE implementation (`_run_by_ref`), not two inline copies
    that can drift. Pins: `_run_by_ref` exists, finds a run by ref / returns None on a miss,
    and `_run_for` agrees with it for the same ref."""

    def test_run_by_ref_finds_matches_and_agrees_with_run_for(self):
        from did_it import evidence
        from did_it.reconcile import _run_by_ref, _run_for

        r0 = evidence.Run(index=0, command="pytest", exit_code=0,
                          output="1 passed\n", ref="aaa", is_test_run=True)
        r1 = evidence.Run(index=1, command="pytest", exit_code=1,
                          output="1 failed\n", ref="bbb", is_test_run=True)
        index = evidence.Index(runs=[r0, r1], changes=[])

        assert _run_by_ref(index, "aaa") is r0
        assert _run_by_ref(index, "bbb") is r1
        assert _run_by_ref(index, "missing") is None

        # _run_for delegates to the same lookup for an Evidence's ref.
        e = evidence.Evidence(tool="Bash", ref="bbb")
        assert _run_for(index, e) is _run_by_ref(index, "bbb") is r1


class TestPartialPassRatio:
    """`N/M passing` with M > N is a partial-failure admission, not a clean pass. Left positive it
    could be asserted against a partially-red run and falsely CONTRADICTED when the count guard
    misses. It must be negative; a full ratio (M == N) stays positive."""

    def test_partial_ratio_is_negative(self):
        from did_it import extraction

        for s in ("12/15 passing", "12/15 tests passing", "3/10 tests pass"):
            c = extraction._classify(s)
            assert c is not None and (c.kind, c.polarity) == ("test-fail", "negative"), s

    def test_full_ratio_stays_positive_with_count(self):
        from did_it import extraction

        c = extraction._classify("15/15 tests passing")
        assert c is not None and (c.kind, c.polarity, c.count) == ("test-pass", "positive", 15)

    def test_partial_ratio_is_not_falsely_accused_on_count_mismatch(self, tmp_path):
        # The run's own passed count (10) != the claim's (12), so the count-corroboration guard
        # does NOT fire; before the fix the positive claim would be CONTRADICTED by the red run.
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "10 passed, 5 failed in 0.30s", exit_code=1)
        b.assistant_text("12/15 tests passing.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "12/15") != Verdict.CONTRADICTED


class TestNegatedProceduralClaims:
    """`file-created`/`command-ran` had no negation gate, so a denial ("never created
    config.py", "never ran the suite") was misread as a POSITIVE claim and could then be
    falsely BACKED — endorsing a claim the author explicitly denied making. A leading
    negation within the verb's own clause must drop the positive claim (safe direction)."""

    def test_negated_file_created_is_not_a_positive_claim(self):
        from did_it import extraction

        for s in ("never created config.py", "no longer wrote config.py",
                  "I hasn't added helper.py"):
            c = extraction._classify(s)
            assert c is None or c.kind != "file-created" or c.polarity != "positive", s

    def test_negated_command_ran_is_not_a_positive_claim(self):
        from did_it import extraction

        for s in ("never ran the suite", "no longer ran the tests",
                  "never executed the migration"):
            c = extraction._classify(s)
            assert c is None or c.kind != "command-ran" or c.polarity != "positive", s

    def test_genuine_procedural_claims_still_classify_positive(self):
        from did_it import extraction

        for s, kind in (("created config.py", "file-created"),
                        ("ran the suite", "command-ran"),
                        # a bare "no"/"not" elsewhere in the sentence must NOT drop it
                        ("I ran the tests, no problem here", "command-ran")):
            c = extraction._classify(s)
            assert c is not None and (c.kind, c.polarity) == (kind, "positive"), s


class TestGreenScopeSymmetry:
    """REV-5: the target and family scope guards protected only the red accusation path; the
    green path backed immediately after the optional count check, so a passing subset or
    another family's suite endorsed a broader claim. Green and red now consult the SAME
    claim-to-run scope decision (`evidence.scope_mismatch`): green mismatches abstain to
    UNSUPPORTED (endorsement precision); red mismatches keep abstaining (accusation
    precision — pinned in test_accusation_guards.py, unchanged)."""

    def test_green_other_family_run_does_not_back_a_family_named_claim(self, tmp_path):
        # REV-5 counterexample 1: a green cargo run is not evidence about pytest.
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("cargo test", "test result: ok. 3 passed; 0 failed; 0 ignored; finished in 0.31s")
        b.assistant_text("All pytest tests pass.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "pytest tests pass") == Verdict.UNSUPPORTED

    def test_green_targeted_run_does_not_back_a_suite_level_claim(self, tmp_path):
        # REV-5 counterexample 2: one passing case is not the whole suite.
        b = SessionBuilder()
        b.user_text("run the repro")
        b.bash("pytest tests/test_repro.py::test_bug -q", "1 passed in 0.05s")
        b.assistant_text("All tests pass.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "tests pass") == Verdict.UNSUPPORTED

    def test_green_multi_family_session_does_not_back_a_generic_claim(self, tmp_path):
        # Both suites ran, the claim names neither: WHICH suite "all tests" covers is
        # ambiguous — the same multi-family abstention the red path applies.
        b = SessionBuilder()
        b.user_text("run both suites")
        b.bash("cargo test", "test result: ok. 3 passed; 0 failed; 0 ignored; finished in 0.31s")
        b.bash("pytest -q", "12 passed in 0.30s")
        b.assistant_text("All tests pass.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "tests pass") == Verdict.UNSUPPORTED

    def test_green_run_of_the_named_family_still_backs(self, tmp_path):
        # The gate must not over-suppress: naming the family that actually ran is a match.
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "12 passed in 0.30s")
        b.assistant_text("All pytest tests pass.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "pytest tests pass") == Verdict.BACKED_TRANSCRIPT

    def test_green_targeted_run_still_backs_a_claim_naming_its_target(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the repro")
        b.bash("pytest tests/test_repro.py -q", "3 passed in 0.05s")
        b.assistant_text("The test_repro.py tests pass.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "test_repro.py tests pass") == Verdict.BACKED_TRANSCRIPT

    def test_green_suite_run_still_backs_a_generic_claim(self, tmp_path):
        # Control: the symmetric gate leaves the hero path untouched.
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "12 passed in 0.30s")
        b.assistant_text("All tests pass.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "tests pass") == Verdict.BACKED_TRANSCRIPT


class TestCompoundExecutionClaims:
    """REV-8: `_command_ran` binds existentially over the sentence's tokens, so a conjunction
    ("I ran pytest and ruff.") was endorsed WHOLESALE after only one component ran. Compound
    execution claims now split into one claim per coordinated command (the review's preferred
    remediation), so partial execution yields per-command receipts — never a whole-conjunction
    endorsement. command-ran never accuses, so every miss here abstains (endorsement
    precision, not the accusation axis)."""

    @staticmethod
    def receipts_for(receipts, fragment):
        return [r for r in receipts if fragment in r.claim_text]

    def test_partial_execution_is_not_endorsed_wholesale(self, tmp_path):
        # The REV-8 counterexample: only pytest ran; the ruff conjunct earns no endorsement.
        b = SessionBuilder()
        b.user_text("run the checks")
        b.bash("pytest -q", "12 passed in 0.30s")
        b.assistant_text("I ran pytest and ruff.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        rs = self.receipts_for(receipts, "pytest and ruff")
        assert [r.verdict for r in rs] == [Verdict.BACKED_TRANSCRIPT, Verdict.UNSUPPORTED]
        # the abstaining receipt names the command that never ran (a useful per-command receipt)
        assert any("ruff" in n for n in rs[1].notes)

    def test_full_execution_earns_a_receipt_per_command(self, tmp_path):
        # Control: when every conjunct ran, each earns its own endorsement.
        b = SessionBuilder()
        b.user_text("run the checks")
        b.bash("pytest -q", "12 passed in 0.30s")
        b.bash("ruff check .", "All checks passed!")
        b.assistant_text("I ran pytest and ruff.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        rs = self.receipts_for(receipts, "pytest and ruff")
        assert [r.verdict for r in rs] == [Verdict.BACKED_TRANSCRIPT, Verdict.BACKED_TRANSCRIPT]

    def test_failed_conjunct_is_reported_per_command(self, tmp_path):
        # Partial FAILURE is also per-command: the failed conjunct abstains with its exit code.
        b = SessionBuilder()
        b.user_text("run the checks")
        b.bash("pytest -q", "12 passed in 0.30s")
        b.bash("ruff check .", "Found 3 errors.", exit_code=1)
        b.assistant_text("I ran pytest and ruff.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        rs = self.receipts_for(receipts, "pytest and ruff")
        assert [r.verdict for r in rs] == [Verdict.BACKED_TRANSCRIPT, Verdict.UNSUPPORTED]
        assert any("exited 1" in n for n in rs[1].notes)

    def test_comma_list_splits_every_conjunct(self, tmp_path):
        # A comma-coordinated list is a conjunction too; only ruff actually ran.
        b = SessionBuilder()
        b.user_text("run the checks")
        b.bash("ruff check .", "All checks passed!")
        b.assistant_text("Ran pytest, ruff, and mypy.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        rs = self.receipts_for(receipts, "Ran pytest, ruff, and mypy")
        assert [r.verdict for r in rs] == [
            Verdict.UNSUPPORTED, Verdict.BACKED_TRANSCRIPT, Verdict.UNSUPPORTED,
        ]

    def test_single_command_with_arguments_is_not_split(self, tmp_path):
        # A non-connective gap ("on") keeps the tokens in ONE conjunct: this sentence
        # describes a single command, so it earns exactly one receipt.
        b = SessionBuilder()
        b.user_text("run the repro")
        b.bash("pytest tests/test_foo.py -q", "3 passed in 0.05s")
        b.assistant_text("Ran pytest on tests/test_foo.py to confirm.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        rs = self.receipts_for(receipts, "Ran pytest on")
        assert [r.verdict for r in rs] == [Verdict.BACKED_TRANSCRIPT]

    def test_split_helper_contract(self):
        # Boundary contract of the splitter itself (per LOOP_LEARNINGS 2026-07-11: test the
        # boundary function's own contract, not only check()'s end-to-end verdict).
        from did_it import extraction

        c = extraction._classify("I ran pytest and ruff.")
        parts = extraction._split_compound(c)
        assert [p.tokens for p in parts] == [["pytest"], ["ruff"]]
        assert all(p.kind == "command-ran" and p.text == c.text for p in parts)

        c2 = extraction._classify("Ran pytest, then ruff.")
        assert [p.tokens for p in extraction._split_compound(c2)] == [["pytest"], ["ruff"]]

        # a single command with its argument is one conjunct — never split
        c3 = extraction._classify("Ran pytest on tests/test_foo.py.")
        assert extraction._split_compound(c3) == [c3]

    def test_split_only_applies_to_command_ran(self):
        # file-created relies on tokens[0] being the claimed path; splitting any other
        # kind would corrupt its binding. The splitter is kind-gated.
        from did_it import extraction

        c = extraction._classify("Created config.py and helper.py")
        assert c is not None and c.kind == "file-created"
        assert extraction._split_compound(c) == [c]


class TestNarrationCoOccurrence:
    def test_checkable_claim_inside_workflow_narration_is_adjudicated(self, tmp_path):
        # 'worktree' vocabulary silently dropped a co-occurring pass-claim.
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "12 passed in 0.30s")
        b.assistant_text("All 12 tests pass in the worktree.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "tests pass") == Verdict.BACKED_TRANSCRIPT

    def test_pure_workflow_narration_still_produces_no_receipt(self, tmp_path):
        b = SessionBuilder()
        b.user_text("continue")
        b.assistant_text("Marked the todo done; the review SIGN-OFF is recorded in the ledger.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert receipts == []


class TestMiscountReadsSummaryLine:
    """The green-branch count check reads the framework summary line, not the whole output.

    A stray `N passed` elsewhere in the output (a setup/plugin line) must not be mistaken for
    the run's pass count and demote a truthful pass-claim to UNSUPPORTED (a lost BACKED — a
    miss, never an accusation). Aligns the green branch with the accusation path, which already
    reads only `evidence.summary_passed_count`.
    """

    def test_stray_passed_line_does_not_demote_a_truthful_count(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "note: 3 passed earlier in setup\n12 passed in 0.30s")
        b.assistant_text("All 12 tests pass.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "tests pass") == Verdict.BACKED_TRANSCRIPT

    def test_genuine_miscount_vs_summary_still_abstains(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "12 passed in 0.30s")
        b.assistant_text("All 13 tests pass.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "tests pass") == Verdict.UNSUPPORTED


class TestPathBindingBoundary:
    """A path token binds only as a whole path segment, not a substring of a longer name.

    `binds_command` feeds command-ran claims (never the accusation path), so an over-bind is
    a false BACKED endorsement, not a false accusation — but BACKED precision is a DoD bar, so
    `app.py` must not bind a command that ran `myapp.py` or `app.pyc`.
    """

    def test_substring_of_a_longer_filename_does_not_bind(self):
        from did_it import evidence as ev
        assert not ev.binds_command(["app.py"], "python myapp.py")     # prefix of a longer name
        assert not ev.binds_command(["app.py"], "rm app.pyc")          # extension continues
        assert not ev.binds_command(["app.py"], "cat app.py.bak")      # dotted continuation

    def test_whole_segment_and_paths_still_bind(self):
        from did_it import evidence as ev
        assert ev.binds_command(["app.py"], "python src/app.py")        # after a '/'
        assert ev.binds_command(["app.py"], "pytest app.py::test_x")    # bounded by ':'
        assert ev.binds_command(["requirements.txt"], "pip install -r requirements.txt")
        assert ev.binds_command(["scripts/migrate.py"], "python scripts/migrate.py --prod")
        assert ev.binds_command(["tests/"], "pytest tests/unit -q")     # directory prefix

    def test_directory_token_does_not_bind_a_longer_dirname(self):
        from did_it import evidence as ev
        assert not ev.binds_command(["tests/"], "pytest mytests/unit")

    def test_over_bound_command_ran_claim_is_unsupported(self, tmp_path):
        b = SessionBuilder()
        b.user_text("migrate")
        b.bash("python myapp.py --prod", "done", exit_code=0)
        b.assistant_text("Ran app.py against prod.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "app.py") == Verdict.UNSUPPORTED


class TestFileCreationEvidence:
    """REV-6: `_file_created` reduced the claim to a basename and accepted ANY mutation
    (Edit/Write/NotebookEdit), so an Edit to `tests/config.py` backed `Created src/config.py.`
    Change events now carry a normalized in-repo path and an operation kind; only a
    create-capable event whose path matches the claimed path (segment-aligned — never
    basename-only when the claim carries a directory) backs a creation claim. File-created
    never accuses, so every miss here abstains (endorsement precision, not the accusation axis)."""

    def test_edit_elsewhere_does_not_back_a_creation_claim(self, tmp_path):
        # The REV-6 counterexample: wrong directory AND wrong operation.
        b = SessionBuilder()
        b.user_text("set up the config")
        b.edit("/work/toy-repo/tests/config.py")
        b.assistant_text("Created src/config.py.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "src/config.py") == Verdict.UNSUPPORTED

    def test_create_in_another_directory_does_not_back_a_directory_claim(self, tmp_path):
        # Create-capable, but the claim carries a directory and it does not match.
        b = SessionBuilder()
        b.user_text("set up the config")
        b.write_file("/work/toy-repo/tests/config.py")
        b.assistant_text("Created src/config.py.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "src/config.py") == Verdict.UNSUPPORTED

    def test_edit_to_the_claimed_path_does_not_back_creation(self, tmp_path):
        # Right path, wrong operation: an edit proves modification, not creation.
        b = SessionBuilder()
        b.user_text("set up the config")
        b.edit("/work/toy-repo/src/config.py")
        b.assistant_text("Created src/config.py.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "src/config.py") == Verdict.UNSUPPORTED

    def test_notebook_edit_does_not_back_creation(self, tmp_path):
        # NotebookEdit mutates an existing notebook; it is not create-capable.
        b = SessionBuilder()
        b.user_text("add the analysis cell")
        b.tool_call("NotebookEdit",
                    {"file_path": "/work/toy-repo/src/analysis.ipynb", "new_source": "x = 1"},
                    "Cell inserted.")
        b.assistant_text("Created src/analysis.ipynb.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "analysis.ipynb") == Verdict.UNSUPPORTED

    def test_create_at_the_claimed_path_still_backs(self, tmp_path):
        # Control: a Write at the claimed path is the honest shape.
        b = SessionBuilder()
        b.user_text("set up the config")
        b.write_file("/work/toy-repo/src/config.py")
        b.assistant_text("Created src/config.py.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "src/config.py") == Verdict.BACKED_TRANSCRIPT

    def test_bare_filename_claim_still_backs_a_create_in_any_directory(self, tmp_path):
        # Control: a claim stating no directory matches by name (the eval corpus shape).
        b = SessionBuilder()
        b.user_text("set up the config")
        b.write_file("/work/toy-repo/src/config.py")
        b.assistant_text("Created config.py.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "config.py") == Verdict.BACKED_TRANSCRIPT

    def test_create_then_edit_still_backs_the_creation_claim(self, tmp_path):
        # Control: a later edit must not shadow the creation (the reverse scan keeps
        # looking for a create event instead of stopping at the newest mutation).
        b = SessionBuilder()
        b.user_text("set up the config")
        b.write_file("/work/toy-repo/src/config.py")
        b.edit("/work/toy-repo/src/config.py")
        b.assistant_text("Created src/config.py.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "src/config.py") == Verdict.BACKED_TRANSCRIPT

    def test_change_events_carry_operation_and_normalized_path(self, tmp_path):
        # The evidence model itself (boundary contract, per LOOP_LEARNINGS 2026-07-11):
        # ops are create / edit / notebook-edit; paths are normalized in-repo (cwd stripped).
        from did_it import evidence, transcript

        b = SessionBuilder()
        b.user_text("build it")
        b.write_file("/work/toy-repo/src/new.py")
        b.edit("/work/toy-repo/tests/config.py")
        b.tool_call("NotebookEdit",
                    {"file_path": "/work/toy-repo/nb/run.ipynb", "new_source": "x"},
                    "Cell inserted.")
        session = transcript.parse(b.write_jsonl(tmp_path / "t.jsonl"))
        index = evidence.build_index(session)
        assert [(c.op, c.path) for c in index.changes] == [
            ("create", "src/new.py"),
            ("edit", "tests/config.py"),
            ("notebook-edit", "nb/run.ipynb"),
        ]


class TestScopeNarrowedEndorsement:
    """L05-01/ADJ-A: a generic green run must not endorse a scope-narrowed claim."""

    def test_generic_green_does_not_endorse_file_scoped_claim(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "12 passed in 0.30s")
        b.assistant_text("The test_nonexistent.py tests pass.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "test_nonexistent.py") == Verdict.UNSUPPORTED

    def test_generic_green_does_not_endorse_adjective_scoped_claim(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "12 passed in 0.30s")
        b.assistant_text("All unit tests pass.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "unit tests pass") == Verdict.UNSUPPORTED

    def test_targeted_green_still_endorses_matching_file(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest tests/test_repro.py", "3 passed in 0.10s")
        b.assistant_text("The test_repro.py tests pass.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "test_repro.py") == Verdict.BACKED_TRANSCRIPT

    def test_directory_green_still_endorses_matching_scope(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest tests/unit/", "8 passed in 0.20s")
        b.assistant_text("All unit tests pass.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "unit tests pass") == Verdict.BACKED_TRANSCRIPT


class TestCoherentCommandBinding:
    """L05-04 / PIR-3 / ADJ-D / ADJ-E: when a claim names a recognized tool, incidental path
    tokens must not substitute for the tool's invocation.  An unrecognized command-like word
    plus a path (L05-DECIDE-5) abstains rather than degrading to path-only evidence."""

    # -- PIR-3: false BACKED via incidental path binding --

    def test_cat_path_does_not_back_a_pytest_exit_code_claim(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run checks")
        b.bash("pytest -q", "2 failed, 10 passed in 0.30s", exit_code=1)
        b.bash("cat report.txt", "some content")
        b.assistant_text("pytest exited with code 0 after I inspected report.txt.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "pytest exited") == Verdict.UNSUPPORTED

    def test_cat_path_does_not_back_a_ran_pytest_claim(self, tmp_path):
        b = SessionBuilder()
        b.user_text("check")
        b.bash("cat tests/test_foo.py", "import pytest")
        b.assistant_text("I ran pytest on tests/test_foo.py.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "ran pytest") == Verdict.UNSUPPORTED

    def test_no_pytest_run_cat_path_does_not_back_exit_code(self, tmp_path):
        b = SessionBuilder()
        b.user_text("check")
        b.bash("cat report.txt", "some content")
        b.assistant_text("pytest exited with code 0 after I inspected report.txt.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "pytest exited") == Verdict.UNSUPPORTED

    # -- ADJ-D: wrapper with path does not back a named-tool claim --

    def test_wrapper_path_does_not_back_pytest_exit_code(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run checks")
        b.bash("pytest -q", "2 failed, 10 passed in 0.30s", exit_code=1)
        b.bash("./scripts/run_tests.sh tests/test_foo.py", "OK")
        b.assistant_text("pytest exited with code 0 on tests/test_foo.py.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "pytest exited") == Verdict.UNSUPPORTED

    # -- ADJ-E: module-invocation phrasing, same mechanism --

    def test_cat_does_not_back_module_pytest_command_ran(self, tmp_path):
        b = SessionBuilder()
        b.user_text("check")
        b.bash("cat src/app.py", "print('hello')")
        b.assistant_text("I executed python -m pytest against src/app.py.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "executed python") == Verdict.UNSUPPORTED

    # -- L05-DECIDE-5: unrecognized command-like word + path --

    def test_unrecognized_tool_plus_path_abstains(self, tmp_path):
        b = SessionBuilder()
        b.user_text("check coverage")
        b.bash("cat src/app.py", "print('hello')")
        b.assistant_text("I ran coverage on src/app.py.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "ran coverage") == Verdict.UNSUPPORTED

    def test_alphanumeric_unrecognized_tool_abstains_flake8(self, tmp_path):
        b = SessionBuilder()
        b.user_text("check")
        b.bash("cat src/app.py", "print('hello')")
        b.assistant_text("I ran flake8 on src/app.py.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "ran flake8") == Verdict.UNSUPPORTED

    def test_alphanumeric_unrecognized_tool_abstains_bandit3(self, tmp_path):
        b = SessionBuilder()
        b.user_text("check")
        b.bash("cat src/app.py", "print('hello')")
        b.assistant_text("I ran bandit3 on src/app.py.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "ran bandit3") == Verdict.UNSUPPORTED

    def test_alphanumeric_unrecognized_tool_abstains_2to3(self, tmp_path):
        b = SessionBuilder()
        b.user_text("check")
        b.bash("cat src/app.py", "print('hello')")
        b.assistant_text("I ran 2to3 on src/app.py.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "ran 2to3") == Verdict.UNSUPPORTED

    def test_dotted_unrecognized_tool_abstains_pylint311(self, tmp_path):
        b = SessionBuilder()
        b.user_text("check")
        b.bash("cat src/app.py", "print('hello')")
        b.assistant_text("I ran pylint3.11 on src/app.py.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "ran pylint3.11") == Verdict.UNSUPPORTED

    def test_dotted_unrecognized_tool_abstains_py_test(self, tmp_path):
        b = SessionBuilder()
        b.user_text("check")
        b.bash("cat src/app.py", "print('hello')")
        b.assistant_text("I ran py.test on src/app.py.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "ran py.test") == Verdict.UNSUPPORTED

    def test_dotted_unrecognized_tool_abstains_python311(self, tmp_path):
        b = SessionBuilder()
        b.user_text("check")
        b.bash("cat src/app.py", "print('hello')")
        b.assistant_text("I ran python3.11 on src/app.py.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "ran python3.11") == Verdict.UNSUPPORTED

    def test_bare_digit_token_is_not_treated_as_command(self, tmp_path):
        b = SessionBuilder()
        b.user_text("check")
        b.bash("cat src/app.py", "print('hello')")
        b.assistant_text("I ran 42 on src/app.py.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "ran 42") == Verdict.BACKED_TRANSCRIPT

    # -- Genuine path-only controls (must stay BACKED) --

    def test_genuine_path_only_claim_still_backs(self, tmp_path):
        b = SessionBuilder()
        b.user_text("migrate")
        b.bash("python scripts/migrate.py --prod", "done")
        b.assistant_text("Ran scripts/migrate.py against prod.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "scripts/migrate.py") == Verdict.BACKED_TRANSCRIPT

    def test_bare_filename_path_only_still_backs(self, tmp_path):
        b = SessionBuilder()
        b.user_text("migrate")
        b.bash("python migrate.py --prod", "done")
        b.assistant_text("Ran migrate.py against prod.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "migrate.py") == Verdict.BACKED_TRANSCRIPT

    # -- Genuine tool bindings (must stay BACKED) --

    def test_genuine_pytest_run_still_backs_command_ran(self, tmp_path):
        b = SessionBuilder()
        b.user_text("verify")
        b.bash("pytest -q", "12 passed in 0.30s")
        b.assistant_text("I ran pytest to verify.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "ran pytest") == Verdict.BACKED_TRANSCRIPT

    def test_genuine_python_m_pytest_still_backs(self, tmp_path):
        b = SessionBuilder()
        b.user_text("verify")
        b.bash("python -m pytest -q", "12 passed in 0.30s")
        b.assistant_text("I ran pytest to verify.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "ran pytest") == Verdict.BACKED_TRANSCRIPT

    def test_genuine_pytest_with_path_backs_when_path_in_command(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the repro")
        b.bash("pytest tests/test_foo.py -q", "3 passed in 0.05s")
        b.assistant_text("Ran pytest on tests/test_foo.py to confirm.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "Ran pytest") == Verdict.BACKED_TRANSCRIPT

    def test_genuine_pytest_exit_code_still_backs(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run checks")
        b.bash("pytest -q", "12 passed in 0.30s")
        b.assistant_text("pytest exited with code 0.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "pytest exited") == Verdict.BACKED_TRANSCRIPT

    def test_exit_code_binds_tool_run_not_incidental_path_run(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run checks")
        b.bash("pytest -q", "2 failed, 10 passed in 0.30s", exit_code=1)
        b.bash("ruff check .", "All checks passed!")
        b.assistant_text("pytest exited with code 1.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "pytest exited") == Verdict.BACKED_TRANSCRIPT

"""BACKED-transcript precision — pins from the 2026-07-10 panel review (C7).

BACKED coverage is a published DoD bar, so a false endorsement corrupts the numbers even
though it is not the accusation axis. Panel probes: substring binding endorses work that
never ran (P6a/P6b), the exit-0 shortcut endorses non-executing invocations (P6c), failed
commands endorse "ran successfully" claims (P6d), and a mis-negated "no failures" claim
turns a red run into an endorsement (P7).
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
        # P6a: 'pytest' as an ARGUMENT is not an invocation.
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
        # P6d: the command ran and FAILED; endorsing "successfully" is a false receipt.
        b = SessionBuilder()
        b.user_text("migrate")
        b.bash("python scripts/migrate.py --prod", "Traceback (most recent call last)...",
               exit_code=1)
        b.assistant_text("Ran scripts/migrate.py against prod successfully.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "migrate.py") == Verdict.UNSUPPORTED

    def test_sentence_final_punctuation_does_not_break_binding(self, tmp_path):
        # seat-4 nit: BIND_TOKEN swallowed the trailing period, so the exactly-matching
        # run never bound. Very common claim shape.
        b = SessionBuilder()
        b.user_text("install")
        b.bash("pip install -r requirements.txt", "Successfully installed 12 packages")
        b.assistant_text("Installed the deps from requirements.txt.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "requirements.txt") == Verdict.BACKED_TRANSCRIPT


class TestNamedCheckBinding:
    def test_grep_for_ruff_does_not_back_a_ruff_clean_claim(self, tmp_path):
        # P6b: mentioning the tool in another command's arguments is not a check run.
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
        # P6c: exit-0 with zero test evidence endorsed "All 500 tests pass."
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
        # P7: misclassified as a negative failure-report, this earned BACKED
        # ("failure honestly reported") on a red run — a lying pass-claim endorsed.
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "1 failed, 11 passed in 0.30s", exit_code=1)
        b.assistant_text("All tests pass, no failures.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "tests pass") == Verdict.CONTRADICTED

    def test_honest_mixed_report_with_no_new_failures_is_not_accused(self, tmp_path):
        # Review round 1: the exemption must not neutralize a LIVE failure admission in
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
        # Review round 1: lowercasing the command killed the env-prefix branch of the
        # position anchor; CI=1/PYTHONPATH= prefixed real runs must stay witnesses.
        b = SessionBuilder()
        b.user_text("typecheck")
        b.bash("CI=1 python -m mypy src", "Success: no issues found in 14 source files")
        b.assistant_text("mypy passes cleanly.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "mypy passes") == Verdict.BACKED_TRANSCRIPT

    def test_env_var_name_is_not_an_invocation(self, tmp_path):
        # Review round 2: `MYPY=1 pytest -q` runs pytest, not mypy — the uppercase env
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
    unrelated EARLIER `;`-clause does not invert a genuine pass (audit 2026-07-10) — while a LIVE
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


class TestNarrationCoOccurrence:
    def test_checkable_claim_inside_workflow_narration_is_adjudicated(self, tmp_path):
        # seat-4: 'worktree' vocabulary silently dropped a co-occurring pass-claim.
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "12 passed in 0.30s")
        b.assistant_text("All 12 tests pass in the worktree.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "tests pass") == Verdict.BACKED_TRANSCRIPT

    def test_pure_workflow_narration_still_produces_no_receipt(self, tmp_path):
        b = SessionBuilder()
        b.user_text("continue")
        b.assistant_text("Marked the todo done; pre-merge-review SIGN-OFF recorded in the ledger.")
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

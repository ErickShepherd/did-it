"""Unit tests for evidence binding — run classification and the temporal guard.

Inner-loop tests (implementation-adjacent, but pinned to real-anchor failure modes
observed 2026-07-10: heredoc/pip phantom test runs, doc-only-edit guard voiding).
"""

from __future__ import annotations

import did_it
from did_it.verdicts import Verdict
from did_it.evidence import is_test_command, target_tokens

from did_it.testing import SessionBuilder


class TestTargetTokens:
    """A -k/-m/-run selector value stops at whitespace/next flag when unquoted, but keeps spaces
    when quoted (audit 2026-07-10). An unrelated trailing flag must not become a bogus target."""

    def test_unquoted_value_stops_before_next_flag(self):
        assert target_tokens("pytest -k foo --verbose") == {"foo"}     # not {"foo", "verbose"}
        assert target_tokens("go test -run TestFoo -v") == {"TestFoo"}  # not {"TestFoo"} + "v"

    def test_quoted_value_keeps_its_spaces(self):
        assert target_tokens('pytest -k "foo or bar" -x') == {"foo", "bar"}

    def test_glued_and_suite_level(self):
        assert target_tokens("pytest -kfoo") == {"foo"}
        assert target_tokens("pytest -q") == set()


class TestIsTestCommand:
    def test_plain_pytest(self):
        assert is_test_command("pytest -q")

    def test_python_module_form(self):
        assert is_test_command(".venv/bin/python -m pytest -q 2>&1 | tail -1")

    def test_after_chain_operator(self):
        assert is_test_command("cd /work/toy && pytest -q")

    def test_heredoc_body_is_not_a_test_run(self):
        cmd = "cat >> NOTES.md <<'EOF'\n`python -m pytest -q` -> 9 passed\nEOF"
        assert not is_test_command(cmd)

    def test_pip_install_pytest_is_not_a_test_run(self):
        assert not is_test_command("pip -q install pytest pytest-cov")

    def test_echoed_runner_is_not_a_test_run(self):
        assert not is_test_command('echo "pytest passed"')

    def test_grep_for_pytest_is_not_a_test_run(self):
        assert not is_test_command("grep -r pytest docs/")

    def test_version_on_a_different_clause_does_not_drop_the_test_run(self):
        # _NON_EXECUTING is checked per-clause: an unrelated `--version` elsewhere must not
        # drop a real test run (audit 2026-07-10). Both operand orderings.
        assert is_test_command("pytest tests/ && node build.js --version")
        assert is_test_command("node build.js --version && pytest tests/")

    def test_version_on_the_runner_clause_still_excludes_it(self):
        assert not is_test_command("pytest --version")
        assert not is_test_command("pytest --version && echo done")


class TestTemporalGuardRelevance:
    def test_doc_only_edit_does_not_void_a_green_run(self, tmp_path):
        b = SessionBuilder()
        b.user_text("test then log")
        b.bash("pytest -q", "12 passed in 0.30s")
        b.edit("/work/toy-repo/LOOP_LEARNINGS.md")  # docs cannot change a test outcome
        b.assistant_text("All 12 tests pass.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        (r,) = [x for x in receipts if "tests pass" in x.claim_text]
        assert r.verdict == Verdict.BACKED_TRANSCRIPT

    def test_code_edit_still_voids(self, tmp_path):
        b = SessionBuilder()
        b.user_text("test then tweak")
        b.bash("pytest -q", "12 passed in 0.30s")
        b.edit("/work/toy-repo/app.py")
        b.assistant_text("All 12 tests pass.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        (r,) = [x for x in receipts if "tests pass" in x.claim_text]
        assert r.verdict == Verdict.UNSUPPORTED

    def test_doc_edit_does_not_shield_a_red_run_from_contradiction(self, tmp_path):
        # symmetry: if doc edits don't void green evidence, they don't void red either
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "1 failed, 11 passed in 0.30s", exit_code=1)
        b.edit("/work/toy-repo/NOTES.md")
        b.assistant_text("All tests pass.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        (r,) = [x for x in receipts if "tests pass" in x.claim_text]
        assert r.verdict == Verdict.CONTRADICTED


class TestMiscount:
    def test_explicit_count_mismatch_demotes_to_unsupported(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "12 passed in 0.30s")
        b.assistant_text("All 13 tests pass.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        (r,) = [x for x in receipts if "tests pass" in x.claim_text]
        assert r.verdict == Verdict.UNSUPPORTED

    def test_count_absent_from_truncated_output_stays_backed(self, tmp_path):
        # `pytest | tail` style runs often lose the summary; a green run is still green
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q >/dev/null && echo done", "done")
        b.assistant_text("All 12 tests pass.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        (r,) = [x for x in receipts if "tests pass" in x.claim_text]
        assert r.verdict == Verdict.BACKED_TRANSCRIPT


class TestAssertivenessGate:
    def test_gerund_lead_intent_narration_is_not_gated(self, tmp_path):
        # "Verifying X..., then committing:" announces intent; it asserts nothing yet.
        b = SessionBuilder()
        b.user_text("continue")
        b.bash("pytest -q", "1 failed in 0.30s", exit_code=1)
        b.assistant_text("Verifying the config-reading tests still pass, then committing:")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert receipts == []

    def test_now_imperative_lead_is_not_gated(self, tmp_path):
        b = SessionBuilder()
        b.user_text("continue")
        b.bash("pytest -q", "1 failed in 0.30s", exit_code=1)
        b.assistant_text("Now re-verify: tests pass, defaults are OFF.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert all(r.verdict != Verdict.CONTRADICTED for r in receipts)


class TestExtractionPatterns:
    def test_bare_count_green_is_a_test_pass_claim(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "45 passed in 0.30s")
        b.assistant_text("All 45 green.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        (r,) = receipts
        assert r.verdict == Verdict.BACKED_TRANSCRIPT

    def test_twine_check_passed_is_a_check_pass_claim(self, tmp_path):
        b = SessionBuilder()
        b.user_text("check the dist")
        b.bash("twine check dist/*", "Checking dist/x-1.0-py3-none-any.whl: PASSED")
        b.assistant_text("twine check passed on all four dists.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        (r,) = receipts
        assert r.verdict == Verdict.BACKED_TRANSCRIPT


class TestIntentPhrases:
    def test_let_me_phrase_is_not_gated(self, tmp_path):
        b = SessionBuilder()
        b.user_text("continue")
        b.bash("pytest -q", "3 passed in 0.1s")
        b.assistant_text(
            "Since this is the last item, let me run a full branch verification "
            "(pytest + ruff + build + twine) to confirm the branch is clean and mergeable."
        )
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert receipts == []

    def test_base_form_write_is_future_intent_not_file_created(self, tmp_path):
        b = SessionBuilder()
        b.user_text("continue")
        b.assistant_text("Next item — write docs/release-checklist.md for the owner-gated tail.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert receipts == []

    def test_past_tense_wrote_is_still_a_file_created_claim(self, tmp_path):
        b = SessionBuilder()
        b.user_text("continue")
        b.write_file("/work/toy-repo/docs/notes.md")
        b.assistant_text("Wrote docs/notes.md with the release steps.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        (r,) = receipts
        assert r.verdict == Verdict.BACKED_TRANSCRIPT


class TestCountCapture:
    def test_count_captured_when_suite_phrase_matches_first(self, tmp_path):
        # "The test suite is green: 13 passed." must still capture 13 for the miscount check.
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "12 passed in 0.30s")
        b.assistant_text("The test suite is green: 13 passed.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        (r,) = receipts
        assert r.verdict == Verdict.UNSUPPORTED  # claimed 13, run shows 12


class TestAssertivenessRecall:
    """The assertiveness gate over-dropped genuine accomplished claims (audit 2026-07-10, recall):
    an adjectival-gerund lead, a completed after/when/once lead, and a bare identifier quote.
    Intent narration, future/conditional leads, and attribution quotes still drop."""

    def _classify(self, s):
        from did_it import extraction
        return extraction.is_assertive(s)

    def test_recovered_accomplished_claims_are_assertive(self):
        for s in ("Passing tests confirm the fix.",
                  "After I fixed the bug, all tests pass.",
                  "When I ran pytest, all 12 tests passed.",
                  'The test "test_foo" passes.'):
            assert self._classify(s) is True, s

    def test_intent_future_and_attribution_still_drop(self):
        for s in ("Verifying the config-reading tests still pass, then committing:",
                  "Once the CI runs, tests will pass.",
                  "If it fails, we should revert.",
                  'He said "this will never work" about the plan.',
                  "Committing the changes now."):
            assert self._classify(s) is False, s


class TestFileCreatedPrepositionBoundary:
    """FILE_CREATED's gap must not cross a preposition: "created a helper to update config.py"
    is about the helper, not config.py (audit 2026-07-10). File-created never accuses, so this
    is a misses-only precision fix."""

    def _classify(self, s):
        from did_it import extraction
        return extraction._classify(s)

    def test_path_after_preposition_is_not_the_created_object(self):
        c = self._classify("created a helper to update config.py")
        assert c is None or c.kind != "file-created"

    def test_direct_object_path_still_binds(self):
        for s, path in [("created config.py", "config.py"),
                        ("added tests/test_foo.py", "tests/test_foo.py"),
                        ("Wrote docs/notes.md with the release steps.", "docs/notes.md")]:
            c = self._classify(s)
            assert c is not None and c.kind == "file-created" and c.tokens[0] == path, s

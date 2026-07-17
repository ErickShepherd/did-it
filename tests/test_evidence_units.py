"""Unit tests for evidence binding — run classification and the temporal guard.

Inner-loop tests (implementation-adjacent, but pinned to failure modes observed in real
transcripts: heredoc/pip phantom test runs, doc-only-edit guard voiding).
"""

from __future__ import annotations

import did_it
from did_it import evidence
from did_it.verdicts import Verdict
from did_it.evidence import Run, classify_outcome, is_test_command, runner_family, target_tokens

from did_it.testing import SessionBuilder


class TestTargetTokens:
    """A -k/-m/-run selector value stops at whitespace/next flag when unquoted, but keeps spaces
    when quoted. An unrelated trailing flag must not become a bogus target."""

    def test_unquoted_value_stops_before_next_flag(self):
        assert target_tokens("pytest -k foo --verbose") == {"foo"}     # not {"foo", "verbose"}
        assert target_tokens("go test -run TestFoo -v") == {"TestFoo"}  # not {"TestFoo"} + "v"

    def test_quoted_value_keeps_its_spaces(self):
        assert target_tokens('pytest -k "foo or bar" -x') == {"foo", "bar"}

    def test_glued_and_suite_level(self):
        assert target_tokens("pytest -kfoo") == {"foo"}
        assert target_tokens("pytest -q") == set()

    def test_heredoc_flood_abstains_quickly_when_called_directly(self):
        # target_tokens strips heredoc bodies via the quadratic HEREDOC regex; every OTHER
        # regex sink gates on _scan_bounded first, but this one did not — an ungated caller
        # (present or future) re-opens the O(n^2) heredoc ReDoS. An unbounded command is
        # not evaluable as a witness, so it names no targets: abstain with the empty set.
        import time

        flooded = "pytest " + "<<X " * 40_000
        assert not evidence._scan_bounded(flooded)  # precondition: this is the unbounded shape
        t0 = time.monotonic()
        assert target_tokens(flooded) == set()
        assert time.monotonic() - t0 < 2.0


class TestScanBoundedName:
    """The fail-closed abstain guard is named for its load-bearing role: a command whose
    scan cost is bounded is evaluable; anything else is never a witness. The old `_strippable`
    name undersold this (it read like a simple 'can be stripped' predicate, not a ReDoS gate)."""

    def test_scan_bounded_is_the_guard_name_not_strippable(self):
        assert hasattr(evidence, "_scan_bounded")
        assert not hasattr(evidence, "_strippable")

    def test_scan_bounded_still_abstains_on_a_flood(self):
        assert evidence._scan_bounded("pytest -q")
        assert not evidence._scan_bounded("pytest " + "&& x " * 200)


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
        # drop a real test run. Both operand orderings.
        assert is_test_command("pytest tests/ && node build.js --version")
        assert is_test_command("node build.js --version && pytest tests/")

    def test_version_on_the_runner_clause_still_excludes_it(self):
        assert not is_test_command("pytest --version")
        assert not is_test_command("pytest --version && echo done")

    def test_newline_separated_version_does_not_drop_the_test_run(self):
        # Bash treats a newline like `;`: a `--version` on a SEPARATE line is a separate
        # sub-command and must not suppress a real runner. Both operand orderings.
        assert is_test_command("pytest tests/\nnode build.js --version")
        assert is_test_command("node build.js --version\npytest tests/")

    def test_backgrounded_version_does_not_drop_the_test_run(self):
        # `&` backgrounds the preceding command — also a clause boundary.
        assert is_test_command("node build.js --version & pytest tests/")

    def test_runner_clause_isolates_the_runner_across_a_newline(self):
        # _runner_clause underlies target_tokens: it must return only the runner's own
        # sub-command, not a neighbouring line, so scopes aren't read across a newline.
        assert target_tokens("cd /work\npytest tests/test_foo.py") == {"test_foo.py"}


class TestRunnerFamilyExecutedClause:
    """REV-4 unit pins: the family comes from the stripped EXECUTED runner clause only.
    Non-executed mentions (echoed words, quoted text, non-executing `--version` forms)
    never set it, and two executing families in one completed call are ambiguous."""

    def test_echoed_runner_mention_does_not_set_the_family(self):
        assert runner_family("echo pytest && go test ./...") == "go"

    def test_every_family_in_non_executed_positions_is_ignored(self):
        # every supported family word rides in echo/quoted (non-executed) positions;
        # only the executed go clause decides
        cmd = ("echo pytest tox cargo rust golang npm jest node rspec ruby mvn java "
               '&& echo "cargo test && npm test" && go test ./...')
        assert runner_family(cmd) == "go"

    def test_two_executed_families_in_one_call_is_none(self):
        assert runner_family("pytest -q && go test ./...") is None

    def test_non_executing_runner_clause_does_not_set_the_family(self):
        assert runner_family("pytest --version && go test ./...") == "go"

    def test_simple_runners_keep_their_family(self):
        for cmd, fam in [("pytest -q", "python"),
                         (".venv/bin/python -m pytest -q", "python"),
                         ("cargo test", "rust"),
                         ("go test ./...", "go"),
                         ("npm test", "js"),
                         ("rspec spec/", "ruby"),
                         ("mvn test", "jvm")]:
            assert runner_family(cmd) == fam, cmd

    def test_unbounded_command_has_no_family(self):
        # not scan-bounded -> not evaluable as a witness -> no family binding either
        assert runner_family("pytest " + "&& x " * 200) is None


class TestTemporalGuardRelevance:
    def test_doc_only_edit_does_not_void_a_green_run(self, tmp_path):
        b = SessionBuilder()
        b.user_text("test then log")
        b.bash("pytest -q", "12 passed in 0.30s")
        b.edit("/work/toy-repo/NOTES.md")  # docs cannot change a test outcome
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
    """The assertiveness gate over-dropped genuine accomplished claims (a recall regression):
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
    is about the helper, not config.py. File-created never accuses, so this
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


class TestNegativeGreenEvidenceLinkage:
    """A negative claim on a green run (-> UNSUPPORTED) carries the same evidence linkage as its
    sibling branches; the ref/tier were dropped before."""

    def test_negative_claim_on_green_run_keeps_evidence_ref(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "12 passed in 0.30s")
        b.assistant_text("2 tests still fail.")
        (r,) = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert r.verdict == Verdict.UNSUPPORTED
        assert r.evidence_ref is not None and r.evidence_tier == "witness"


class TestSummaryLinesCaching:
    """`_summary_lines` (splitlines + per-line regex over uncapped tool output) is recomputed
    several times inside a single `classify_outcome` (framework_failed/green/contradiction_span
    each re-scan). Caching it to the instance must not change any verdict — it only stops the
    redundant re-scans. Pinned by counting `_is_summary_line` invocations: with the scan cached,
    it runs exactly once per output line across a whole `classify_outcome`; recomputed, several
    times that."""

    def test_summary_scan_runs_once_per_line_across_classify_outcome(self, monkeypatch):
        run = Run(index=0, command="pytest", exit_code=1,
                  output="1 failed in 0.50s\n", ref="x", is_test_run=True)
        calls = {"n": 0}
        real = evidence._is_summary_line

        def counting(line):
            calls["n"] += 1
            return real(line)

        monkeypatch.setattr(evidence, "_is_summary_line", counting)
        classify_outcome(run)
        assert calls["n"] == len(run.output.splitlines())

    def test_caching_preserves_outcomes(self):
        # A red, a green, and a conflicting-summary run classify exactly as before.
        red = Run(index=0, command="pytest", exit_code=1,
                  output="1 failed in 0.50s\n", ref="a", is_test_run=True)
        green = Run(index=0, command="pytest", exit_code=0,
                    output="12 passed in 0.30s\n", ref="b", is_test_run=True)
        conflict = Run(index=0, command="pytest", exit_code=0,
                       output="12 passed in 0.30s\n2 failed in 0.10s\n", ref="c", is_test_run=True)
        assert classify_outcome(red)[0] == "red"
        assert classify_outcome(green)[0] == "green"
        assert classify_outcome(conflict)[0] == "ambiguous"


class TestClaimScopeTokens:
    """Unit tests for _claim_scope_tokens — narrowing token extraction."""

    def test_generic_claim_has_no_scope_tokens(self):
        from did_it.extraction import Claim
        c = Claim(text="All tests pass.", utterance_index=0, tokens=[])
        assert evidence._claim_scope_tokens(c) == []

    def test_adjective_narrowing(self):
        from did_it.extraction import Claim
        c = Claim(text="All unit tests pass.", utterance_index=0, tokens=[])
        assert "unit" in evidence._claim_scope_tokens(c)

    def test_integration_adjective(self):
        from did_it.extraction import Claim
        c = Claim(text="All integration tests pass.", utterance_index=0, tokens=[])
        assert "integration" in evidence._claim_scope_tokens(c)

    def test_possessive_narrowing(self):
        from did_it.extraction import Claim
        c = Claim(text="The plugin's tests pass.", utterance_index=0, tokens=[])
        assert "plugin" in evidence._claim_scope_tokens(c)

    def test_file_token_narrowing(self):
        from did_it.extraction import Claim
        c = Claim(text="The test_repro.py tests pass.", utterance_index=0, tokens=["test_repro.py"])
        assert "test_repro.py" in evidence._claim_scope_tokens(c)

    def test_runner_family_not_narrowing(self):
        from did_it.extraction import Claim
        c = Claim(text="All pytest tests pass.", utterance_index=0, tokens=["pytest"])
        tokens = evidence._claim_scope_tokens(c)
        assert "pytest" not in tokens

    def test_count_not_narrowing(self):
        from did_it.extraction import Claim
        c = Claim(text="All 12 tests pass.", utterance_index=0, tokens=[])
        assert evidence._claim_scope_tokens(c) == []


class TestRunCoversScope:
    """Unit tests for _run_covers_scope — segment-level coverage check."""

    def test_generic_run_does_not_cover_unit(self):
        run = Run(index=0, command="pytest -q", exit_code=1,
                  output="1 failed, 11 passed in 0.30s\n", ref="a", is_test_run=True)
        assert not evidence._run_covers_scope(run, ["unit"])

    def test_directory_targeted_run_covers_unit(self):
        run = Run(index=0, command="pytest tests/unit/", exit_code=1,
                  output="1 failed in 0.30s\n", ref="a", is_test_run=True)
        assert evidence._run_covers_scope(run, ["unit"])

    def test_failed_line_covers_file_token(self):
        run = Run(index=0, command="pytest -q", exit_code=1,
                  output="FAILED tests/test_repro.py::test_x\n1 failed in 0.30s\n",
                  ref="a", is_test_run=True)
        assert evidence._run_covers_scope(run, ["test_repro.py"])

    def test_failed_line_different_file_does_not_cover(self):
        run = Run(index=0, command="pytest -q", exit_code=1,
                  output="FAILED tests/test_other.py::test_x\n1 failed in 0.30s\n",
                  ref="a", is_test_run=True)
        assert not evidence._run_covers_scope(run, ["test_repro.py"])

    def test_failed_line_in_unit_dir_covers_unit(self):
        run = Run(index=0, command="pytest -q", exit_code=1,
                  output="FAILED tests/unit/test_foo.py::test_x\n1 failed in 0.30s\n",
                  ref="a", is_test_run=True)
        assert evidence._run_covers_scope(run, ["unit"])

    def test_empty_scope_always_covered(self):
        run = Run(index=0, command="pytest -q", exit_code=1,
                  output="1 failed\n", ref="a", is_test_run=True)
        assert evidence._run_covers_scope(run, [])

    def test_substring_not_segment(self):
        run = Run(index=0, command="pytest -q", exit_code=1,
                  output="FAILED tests/unittest_helpers.py::test_x\n1 failed in 0.30s\n",
                  ref="a", is_test_run=True)
        assert not evidence._run_covers_scope(run, ["unit"])


class TestQuantityExtraction:
    """L05-03: quantity metadata on determiner-scoped and ratio claims."""

    def test_some_quantity(self):
        from did_it.extraction import _classify
        c = _classify("Some tests pass.")
        assert c is not None and c.quantity == "some"

    def test_no_quantity(self):
        from did_it.extraction import _classify
        c = _classify("No tests pass.")
        assert c is not None and c.quantity == "no"

    def test_most_quantity(self):
        from did_it.extraction import _classify
        c = _classify("Most tests pass.")
        assert c is not None and c.quantity == "most"

    def test_only_n_quantity_and_count(self):
        from did_it.extraction import _classify
        c = _classify("Only 3 tests pass.")
        assert c is not None and c.quantity == "only" and c.count == 3

    def test_ratio_quantity_and_counts(self):
        from did_it.extraction import _classify
        c = _classify("3 of the 12 tests pass.")
        assert c is not None and c.quantity == "ratio"
        assert c.count == 3 and c.claimed_total == 12

    def test_not_all_quantity(self):
        from did_it.extraction import _classify
        c = _classify("Not all tests pass.")
        assert c is not None and c.quantity == "not_all"

    def test_not_quite_all_quantity(self):
        from did_it.extraction import _classify
        c = _classify("Not quite all tests pass.")
        assert c is not None and c.quantity == "not_quite_all"

    def test_vague_quantifiers(self):
        from did_it.extraction import _classify
        for s in ("Several tests pass.", "Barely any tests pass.",
                  "A couple of tests pass.", "A handful of tests pass."):
            c = _classify(s)
            assert c is not None and c.quantity == "vague", s

    def test_nearly_almost_are_vague(self):
        from did_it.extraction import _classify
        for s in ("Nearly all tests pass.", "Almost all tests pass."):
            c = _classify(s)
            assert c is not None and c.quantity == "vague", s

    def test_positive_claim_has_no_quantity(self):
        from did_it.extraction import _classify
        c = _classify("All tests pass.")
        assert c is not None and c.quantity is None


class TestPartialQuantityCorroboration:
    """L05-03 / PIR-4 / ADJ-F: red runs must not endorse quantitatively false partial claims."""

    def test_some_requires_passed_gt_zero(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "2 failed, 0 passed in 0.30s", exit_code=1)
        b.assistant_text("Some tests pass.")
        (r,) = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert r.verdict == Verdict.UNSUPPORTED

    def test_some_backed_when_passed_gt_zero(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "9 failed, 3 passed in 0.30s", exit_code=1)
        b.assistant_text("Some tests pass.")
        (r,) = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert r.verdict == Verdict.BACKED_TRANSCRIPT

    def test_no_requires_passed_eq_zero(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "2 failed, 10 passed in 0.30s", exit_code=1)
        b.assistant_text("No tests pass.")
        (r,) = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert r.verdict == Verdict.UNSUPPORTED

    def test_no_backed_when_passed_eq_zero(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "2 failed, 0 passed in 0.30s", exit_code=1)
        b.assistant_text("No tests pass.")
        (r,) = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert r.verdict == Verdict.BACKED_TRANSCRIPT

    def test_most_requires_majority(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "9 failed, 3 passed in 0.30s", exit_code=1)
        b.assistant_text("Most tests pass.")
        (r,) = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert r.verdict == Verdict.UNSUPPORTED

    def test_most_backed_when_majority(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "2 failed, 10 passed in 0.30s", exit_code=1)
        b.assistant_text("Most tests pass.")
        (r,) = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert r.verdict == Verdict.BACKED_TRANSCRIPT

    def test_most_ambiguous_denominator_abstains(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "2 failed, 10 passed, 3 skipped in 0.30s", exit_code=1)
        b.assistant_text("Most tests pass.")
        (r,) = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert r.verdict == Verdict.UNSUPPORTED

    def test_only_n_requires_exact_count(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "2 failed, 10 passed in 0.30s", exit_code=1)
        b.assistant_text("Only 3 tests pass.")
        (r,) = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert r.verdict == Verdict.UNSUPPORTED

    def test_only_n_backed_when_count_matches(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "9 failed, 3 passed in 0.30s", exit_code=1)
        b.assistant_text("Only 3 tests pass.")
        (r,) = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert r.verdict == Verdict.BACKED_TRANSCRIPT

    def test_ratio_requires_exact_agreement(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "12 failed, 0 passed in 0.30s", exit_code=1)
        b.assistant_text("3 of the 12 tests pass.")
        (r,) = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert r.verdict == Verdict.UNSUPPORTED

    def test_ratio_backed_when_exact(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "9 failed, 3 passed in 0.30s", exit_code=1)
        b.assistant_text("3 of the 12 tests pass.")
        (r,) = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert r.verdict == Verdict.BACKED_TRANSCRIPT

    def test_nearly_all_is_vague_abstains(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "99 failed, 1 passed in 0.30s", exit_code=1)
        b.assistant_text("Nearly all tests pass.")
        (r,) = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert r.verdict == Verdict.UNSUPPORTED

    def test_almost_all_is_vague_abstains(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "99 failed, 1 passed in 0.30s", exit_code=1)
        b.assistant_text("Almost all tests pass.")
        (r,) = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert r.verdict == Verdict.UNSUPPORTED

    def test_not_all_backed_on_red(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "2 failed, 10 passed in 0.30s", exit_code=1)
        b.assistant_text("Not all tests pass.")
        (r,) = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert r.verdict == Verdict.BACKED_TRANSCRIPT

    def test_not_quite_all_backed_on_red(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "2 failed, 10 passed in 0.30s", exit_code=1)
        b.assistant_text("Not quite all tests pass.")
        (r,) = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert r.verdict == Verdict.BACKED_TRANSCRIPT

    def test_missing_passed_count_abstains(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "2 failed in 0.30s", exit_code=1)
        b.assistant_text("Some tests pass.")
        (r,) = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert r.verdict == Verdict.UNSUPPORTED


class TestSummaryCleanCounts:
    """L05-DECIDE-3: summary_clean_counts only returns counts when passed and failed are
    the only test-outcome categories."""

    def test_clean_summary(self):
        run = Run(index=0, command="pytest", exit_code=1,
                  output="9 failed, 3 passed in 0.30s\n", ref="a", is_test_run=True)
        assert evidence.summary_clean_counts(run) == (3, 9)

    def test_skipped_makes_ambiguous(self):
        run = Run(index=0, command="pytest", exit_code=1,
                  output="2 failed, 10 passed, 3 skipped in 0.30s\n", ref="a", is_test_run=True)
        assert evidence.summary_clean_counts(run) is None

    def test_errors_make_ambiguous(self):
        run = Run(index=0, command="pytest", exit_code=1,
                  output="2 failed, 10 passed, 1 error in 0.30s\n", ref="a", is_test_run=True)
        assert evidence.summary_clean_counts(run) is None

    def test_warnings_ignored(self):
        run = Run(index=0, command="pytest", exit_code=1,
                  output="2 failed, 10 passed, 5 warnings in 0.30s\n", ref="a", is_test_run=True)
        assert evidence.summary_clean_counts(run) == (10, 2)

    def test_no_summary_returns_none(self):
        run = Run(index=0, command="pytest", exit_code=1,
                  output="FAILED tests/test_foo.py::test_x\n", ref="a", is_test_run=True)
        assert evidence.summary_clean_counts(run) is None

    def test_missing_passed_returns_none(self):
        run = Run(index=0, command="pytest", exit_code=1,
                  output="2 failed in 0.30s\n", ref="a", is_test_run=True)
        assert evidence.summary_clean_counts(run) is None

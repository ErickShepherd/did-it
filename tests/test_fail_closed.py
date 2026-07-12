"""Fail-closed hardening — pins the crash-safety and untrusted-input hardening cases.

The exit-code contract reserves 1 for CONTRADICTED. Any crash that escapes the pipeline
exits 1 too, so an exit-code consumer reads a byte-corrupt file as an accusation.
A quadratic regex on untrusted output hangs the Stop hook. Untrusted prose flows raw
into the receipt table, so ANSI/bidi controls can visually rewrite it.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

import did_it
from did_it import cli, hook, report, transcript
from did_it.testing import SessionBuilder
from did_it.verdicts import Receipt, Verdict


class TestParseFailsClosedOnPathologicalJson:
    """transcript.parse must fail closed at ITS OWN boundary (raise ParseFailure), not just
    behind check()'s wrapper. json.loads raises siblings
    of JSONDecodeError on two tiny adversarial inputs — both escaped the old narrow catch.
    """

    def test_deeply_nested_json_line_raises_parsefailure_not_recursionerror(self, tmp_path):
        p = tmp_path / "t.jsonl"
        p.write_text("[" * 100_000 + "]" * 100_000 + "\n")  # RecursionError in the C decoder
        with pytest.raises(transcript.ParseFailure):
            transcript.parse(p)

    def test_huge_integer_line_raises_parsefailure_not_valueerror(self, tmp_path):
        p = tmp_path / "t.jsonl"
        p.write_text("1" * 5000 + "\n")  # ValueError: exceeds int_max_str_digits
        with pytest.raises(transcript.ParseFailure):
            transcript.parse(p)

    def test_end_to_end_check_is_not_evaluable(self, tmp_path):
        # Belt-and-suspenders: the whole pipeline stays NOT-EVALUABLE, never a raise.
        p = tmp_path / "t.jsonl"
        p.write_text("1" * 5000 + "\n")
        (r,) = did_it.check(p)
        assert r.verdict == Verdict.NOT_EVALUABLE


class TestTranscriptSizeCap:
    """A GB-scale .jsonl must fail closed (ParseFailure) BEFORE the whole-file read, not crash
    with MemoryError. The cap is checked via stat, so the
    test shrinks the cap rather than writing a giant file.
    """

    def _valid_session_file(self, tmp_path) -> Path:
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "12 passed in 0.30s")
        b.assistant_text("All 12 tests pass.")
        return b.write_jsonl(tmp_path / "t.jsonl")

    def test_oversize_file_is_parsefailure(self, tmp_path, monkeypatch):
        p = self._valid_session_file(tmp_path)
        monkeypatch.setattr(transcript, "_MAX_TRANSCRIPT_BYTES", 10)  # below the file size
        with pytest.raises(transcript.ParseFailure, match="exceeds"):
            transcript.parse(p)

    def test_file_under_cap_still_parses(self, tmp_path):
        # Positive control: a normal file (well under the real 256 MiB cap) parses fine.
        session = transcript.parse(self._valid_session_file(tmp_path))
        assert session.records  # parsed at least one message record

    def test_oversize_file_is_not_evaluable_end_to_end(self, tmp_path, monkeypatch):
        p = self._valid_session_file(tmp_path)
        monkeypatch.setattr(transcript, "_MAX_TRANSCRIPT_BYTES", 10)
        (r,) = did_it.check(p)
        assert r.verdict == Verdict.NOT_EVALUABLE


class TestVersionParsingFailsClosed:
    """_version_tuple must fail closed to None (unsupported), never crash on a crafted version.
    str.isdigit() accepted Unicode digits int()
    rejects, and a huge all-decimal part trips int()'s int_max_str_digits limit.
    """

    def test_unicode_digit_version_returns_none_not_valueerror(self):
        assert transcript._version_tuple("2.1.²") is None  # '²'.isdigit() is True
        assert transcript.is_supported_version("2.1.²") is False

    def test_huge_decimal_version_part_returns_none_not_valueerror(self):
        assert transcript._version_tuple("2.1." + "1" * 5000) is None

    def test_valid_version_still_parses(self):
        assert transcript._version_tuple("2.1.204") == (2, 1, 204)

    def test_crafted_version_record_is_unknownschema_not_a_crash(self, tmp_path):
        import json

        p = tmp_path / "t.jsonl"
        rec = {
            "type": "assistant",
            "uuid": "fx-ver",
            "parentUuid": None,
            "version": "2.1.²",
            "isSidechain": False,
            "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
        }
        p.write_text(json.dumps(rec) + "\n")
        with pytest.raises(transcript.UnknownSchema):
            transcript.parse(p)


class TestSupportedRangeEndpoints:
    """SRV5 — the version gate is pinned on BOTH sides: each range endpoint parses in-range, and
    the version one step outside each endpoint fails closed to UnknownSchema. A consistency test
    keeps SUPPORTED_SCHEMA_VERSIONS from drifting away from SUPPORTED_SCHEMA_RANGE's endpoints
    (the two constants move together or not at all).
    Policy: docs/design/schema-range-validation.md (SRV1, SRV5).
    """

    def _session_at(self, tmp_path, version) -> Path:
        b = SessionBuilder(version=version)
        b.user_text("run the tests")
        b.bash("pytest -q", "12 passed in 0.30s")
        b.assistant_text("All 12 tests pass.")
        return b.write_jsonl(tmp_path / "t.jsonl")

    @pytest.mark.parametrize("version", ["2.1.156", "2.1.207"])
    def test_range_endpoints_parse_in_range(self, tmp_path, version):
        session = transcript.parse(self._session_at(tmp_path, version))
        assert session.schema_version == version
        assert session.records  # ingested, not failed closed

    @pytest.mark.parametrize("version", ["2.1.155", "2.1.208"])
    def test_one_step_outside_each_endpoint_is_unknownschema(self, tmp_path, version):
        with pytest.raises(transcript.UnknownSchema):
            transcript.parse(self._session_at(tmp_path, version))

    def test_supported_versions_render_the_range_endpoints(self):
        # SUPPORTED_SCHEMA_VERSIONS is a scaffold-compat mirror of the range's endpoints; a bump
        # that edits one constant but not the other must fail here, not ship a silent mismatch.
        lo, hi = transcript.SUPPORTED_SCHEMA_RANGE
        assert transcript.SUPPORTED_SCHEMA_VERSIONS == (
            ".".join(map(str, lo)),
            ".".join(map(str, hi)),
        )


def verdict_of(receipts, fragment):
    (r,) = [x for x in receipts if fragment in x.claim_text]
    return r.verdict


# --- non-UTF-8 bytes must be NOT-EVALUABLE, never exit 1 ---------------------------


class TestNonUtf8:
    def _garbage(self, tmp_path) -> Path:
        p = tmp_path / "t.jsonl"
        p.write_bytes(b"\xff\xfe not a transcript \x80\x81\n")
        return p

    def test_check_returns_session_not_evaluable(self, tmp_path):
        receipts = did_it.check(self._garbage(tmp_path))
        (r,) = receipts
        assert r.verdict == Verdict.NOT_EVALUABLE

    def test_cli_exits_zero_not_the_accusation_code(self, tmp_path, capsys):
        assert cli.main([str(self._garbage(tmp_path))]) == 0

    def test_stop_hook_stays_advisory(self, tmp_path, capsys):
        assert hook.run_stop_hook({"transcript_path": str(self._garbage(tmp_path))}) == 0


class TestCheckFailClosedBackstop:
    """check() is itself the fail-closed source for direct library callers, not just the CLI/hook
    wrappers (__init__.check). An unexpected crash in any pipeline stage must
    become one session-level NOT-EVALUABLE receipt, never propagate. OSError (missing/unreadable
    file) still propagates as a usage error, per the documented contract.
    """

    def _green_session(self, tmp_path) -> Path:
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "12 passed in 0.30s")
        b.assistant_text("All 12 tests pass.")
        return b.write_jsonl(tmp_path / "t.jsonl")

    def test_unexpected_extraction_error_is_not_evaluable_not_a_raise(self, tmp_path, monkeypatch):
        from did_it import extraction

        def boom(*_a, **_k):
            raise RuntimeError("synthetic extraction crash")

        p = self._green_session(tmp_path)
        monkeypatch.setattr(extraction, "extract_claims", boom)
        (r,) = did_it.check(p)
        assert r.verdict == Verdict.NOT_EVALUABLE
        assert any("RuntimeError" in n for n in r.notes)

    def test_unexpected_reconcile_error_is_not_evaluable_not_a_raise(self, tmp_path, monkeypatch):
        from did_it import reconcile

        monkeypatch.setattr(reconcile, "reconcile", lambda *_a, **_k: 1 / 0)
        (r,) = did_it.check(self._green_session(tmp_path))
        assert r.verdict == Verdict.NOT_EVALUABLE
        assert any("ZeroDivisionError" in n for n in r.notes)

    def test_unexpected_parse_error_is_not_evaluable_not_a_raise(self, tmp_path, monkeypatch):
        from did_it import transcript

        def boom(*_a, **_k):
            raise RecursionError("synthetic deep-nesting crash")

        p = self._green_session(tmp_path)
        monkeypatch.setattr(transcript, "parse", boom)
        (r,) = did_it.check(p)
        assert r.verdict == Verdict.NOT_EVALUABLE
        assert any("RecursionError" in n for n in r.notes)

    def test_missing_file_still_propagates_oserror(self, tmp_path):
        import pytest

        with pytest.raises(OSError):
            did_it.check(tmp_path / "does-not-exist.jsonl")


class TestInternalErrorBackstop:
    def test_cli_unexpected_exception_is_usage_error_not_accusation(self, tmp_path, capsys, monkeypatch):
        p = tmp_path / "t.jsonl"
        p.write_text("{}\n")
        monkeypatch.setattr(did_it, "check", lambda *_a, **_k: 1 / 0)
        assert cli.main([str(p)]) == 2

    def test_hook_unexpected_exception_returns_zero(self, tmp_path, capsys, monkeypatch):
        p = tmp_path / "t.jsonl"
        p.write_text("{}\n")
        monkeypatch.setattr(did_it, "check", lambda *_a, **_k: 1 / 0)
        assert hook.run_stop_hook({"transcript_path": str(p)}) == 0

    def test_cli_render_crash_is_usage_error_not_accusation(self, tmp_path, capsys, monkeypatch):
        # report.render handles untrusted transcript text; if it raises, the crash must not
        # escape main() to CPython's default exit 1 (reserved for CONTRADICTED). Exit 2.
        p = tmp_path / "t.jsonl"
        p.write_text("{}\n")
        monkeypatch.setattr(report, "render", lambda *_a, **_k: 1 / 0)
        assert cli.main([str(p)]) == 2


# --- malformed block internals must not crash build_index --------------------------


class TestJsonLegalSeparators:
    def test_unicode_line_separator_in_prose_does_not_kill_the_session(self, tmp_path):
        # U+2028/U+2029/NEL are legal UNESCAPED inside JSON strings and appear in real
        # tool output; splitting on them fragments a valid line and silently turns the
        # whole session NOT-EVALUABLE — masking every genuine verdict.
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "12 passed in 0.30s")
        b.assistant_text("All 12 tests pass. Details follow. And NEL:done.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "tests pass") == Verdict.BACKED_TRANSCRIPT


class TestMalformedBlocks:
    def test_non_dict_tool_input_does_not_crash(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.tool_call("Bash", ["not", "a", "dict"], "12 passed in 0.30s")  # type: ignore[arg-type]
        b.assistant_text("All tests pass.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        # adjudicates (input treated as absent) — the claim simply finds no test run
        assert verdict_of(receipts, "tests pass") == Verdict.UNSUPPORTED

    def test_non_string_text_block_does_not_crash(self, tmp_path):
        b = SessionBuilder()
        b.user_text("hi")
        b.records.append(
            {
                "type": "assistant",
                "uuid": "fx-bad",
                "parentUuid": None,
                "version": "2.1.204",
                "isSidechain": False,
                "message": {"role": "assistant", "content": [{"type": "text", "text": ["boom"]}]},
            }
        )
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert receipts == []


# --- summary scanning must stay linear on adversarial output -----------------------


class TestConflictingSummaries:
    """The highest-severity false-CONTRADICTED path (evidence.framework_failed).

    A stale/echoed summary-SHAPED failure line (`N failed … in Ns`) beside a genuine green
    summary, paired with a non-zero compound-tail exit, satisfied all three D4 gates and no
    guard caught it. Conflicting summaries must abstain (UNSUPPORTED), never accuse — while a
    single mixed summary line (a genuine partial failure) must still accuse.
    """

    def test_stale_echoed_failure_summary_beside_green_does_not_accuse(self, tmp_path):
        # A count-LESS claim so the count-corroboration accusation guard does not fire — this
        # is the residual path: green summary + stale failed summary + red
        # compound-tail exit sails through every guard to a false CONTRADICTED.
        b = SessionBuilder()
        b.user_text("test then deploy")
        b.bash(
            "pytest -q ; cat ci-history.log ; ./deploy.sh",
            "12 passed in 0.30s\n"
            + "----- cat ci-history.log -----\n"
            + "=== 5 failed, 3 passed in 12.01s ===\n",
            exit_code=1,  # the ./deploy.sh tail owns the non-zero exit, not the tests
        )
        b.assistant_text("All tests pass.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        # conflicting green + failed summaries -> ambiguous -> abstain, NEVER CONTRADICTED
        assert verdict_of(receipts, "tests pass") == Verdict.UNSUPPORTED

    def test_single_mixed_summary_line_still_accuses(self, tmp_path):
        # A genuine partial failure is ONE summary line carrying both counts — no green-only
        # line, so it is not a conflict and must still be caught.
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "5 failed, 3 passed in 12.01s", exit_code=1)
        b.assistant_text("All tests pass.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "tests pass") == Verdict.CONTRADICTED

    def test_conflicting_summaries_under_a_masked_exit_do_not_endorse(self, tmp_path):
        # the conflict guard sets framework_failed=False, which also disabled
        # the masked-exit guard — so a `... || true` run with a green AND a failed summary
        # fell through to the exit-0 green branch and endorsed a fake pass. A conflict must be
        # ambiguous in BOTH exit directions: never CONTRADICTED, and never BACKED.
        b = SessionBuilder()
        b.user_text("run both suites")
        b.bash(
            "pytest tests/a -q && pytest tests/b -q || true",
            "3 passed in 0.10s\n=== 2 failed, 8 passed in 0.40s ===\n",
            exit_code=0,  # masked
        )
        b.assistant_text("All tests pass.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "tests pass") == Verdict.UNSUPPORTED


class TestPathologicalOutput:
    def test_huge_near_match_single_line_adjudicates_quickly(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q", "9 passed " * 20_000, exit_code=1)  # ~180KB single line
        b.assistant_text("All tests pass.")
        t0 = time.monotonic()
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert time.monotonic() - t0 < 2.0
        # no summary line, no failure marker -> ambiguous -> abstain
        assert verdict_of(receipts, "tests pass") == Verdict.UNSUPPORTED

    def test_green_summary_beyond_any_cap_still_protects_the_claim(self, tmp_path):
        # a genuine green summary followed by >256KB of echoed log with a
        # stale FAILED line and a red compound tail must stay green — a scan cap that
        # drops the summary re-opens the false accusation it exists to prevent.
        b = SessionBuilder()
        b.user_text("test then deploy")
        b.bash(
            "pytest -q ; ./deploy.sh",
            "12 passed in 0.30s\n"
            + ("verbose build log line\n" * 20_000)
            + "FAILED tests/test_x.py::test_foo\n",
            exit_code=1,
        )
        b.assistant_text("All 12 tests pass.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "tests pass") == Verdict.BACKED_TRANSCRIPT

    def test_multi_megabyte_output_adjudicates_quickly(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        noise = ("verbose log line without summary markers\n" * 50_000) + "12 passed in 0.30s"
        b.bash("pytest -q", noise)
        b.assistant_text("All 12 tests pass.")
        t0 = time.monotonic()
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert time.monotonic() - t0 < 2.0
        assert verdict_of(receipts, "tests pass") == Verdict.BACKED_TRANSCRIPT


# --- receipt rendering must neutralize terminal-control content --------------------


class TestPathologicalCommands:
    def test_heredoc_opener_flood_adjudicates_quickly_and_abstains(self, tmp_path):
        # The HEREDOC-stripping regex is quadratic on unterminated openers (15.5s at 160KB).
        # An un-strippable command is not evaluable as a witness at all —
        # no run, no accusation, pure abstention.
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest " + "<<X " * 40_000, "1 failed in 0.30s", exit_code=1)
        b.assistant_text("All tests pass.")
        t0 = time.monotonic()
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert time.monotonic() - t0 < 2.0
        assert verdict_of(receipts, "tests pass") == Verdict.UNSUPPORTED

    def test_single_heredoc_opener_with_huge_word_adjudicates_quickly(self, tmp_path):
        # A SINGLE `<<` opener followed by a long unbroken word with no terminator made the
        # HEREDOC delimiter capture `(\w+)` backtrack quadratically (3.6s at 40KB -> hours at
        # 1MB). The opener-COUNT cap missed it (only one opener); the delimiter length gate
        # fixes it.
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest <<" + "A" * 100_000, "1 failed in 0.30s", exit_code=1)
        b.assistant_text("All tests pass.")
        t0 = time.monotonic()
        did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert time.monotonic() - t0 < 2.0


class TestPathologicalProse:
    def test_dotless_multi_kb_prose_line_adjudicates_quickly(self, tmp_path):
        # CHECK_PASS/FILE_CREATED lazy `[^.;]*?` scans were O(n^2) on a dotless multi-KB
        # assistant line (3.8s at 32KB -> minutes larger); the per-sentence cap bounds them.
        # A real claim is short, so the cap never drops one.
        b = SessionBuilder()
        b.user_text("status")
        b.assistant_text("ruff " + "a" * 50_000)  # dotless, no terminator, ~50KB
        t0 = time.monotonic()
        did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert time.monotonic() - t0 < 2.0

    def test_short_check_pass_claim_still_classifies(self, tmp_path):
        b = SessionBuilder()
        b.user_text("lint")
        b.bash("ruff check src", "All checks passed!")
        b.assistant_text("ruff is clean.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "ruff is clean") == Verdict.BACKED_TRANSCRIPT


class TestOperatorFloodCommands:
    def test_chain_operator_flood_adjudicates_quickly_and_abstains(self, tmp_path):
        # TEST_RUNNERS anchors at every chain operator and greedily scans from each — an
        # && flood is quadratic (26s at 160KB). A flooded
        # command is not evaluable as a witness at all: no run, no accusation.
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest -q && " * 30_000, "1 failed in 0.30s", exit_code=1)
        b.assistant_text("All tests pass.")
        t0 = time.monotonic()
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert time.monotonic() - t0 < 2.0
        assert verdict_of(receipts, "tests pass") == Verdict.UNSUPPORTED

    def test_newline_flood_adjudicates_quickly(self, tmp_path):
        # ^ anchors at every line under re.M: same quadratic family.
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash(("\n" * 50_000) + "pytest -q", "1 failed in 0.30s", exit_code=1)
        b.assistant_text("All tests pass.")
        t0 = time.monotonic()
        did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert time.monotonic() - t0 < 2.0

    def test_subshell_and_backtick_floods_adjudicate_quickly(self, tmp_path):
        # $( and ` are runner-matcher anchors too — both were still
        # quadratic (14s at 160KB) with only &&/;/|/newline counted.
        import time as _t

        for flood in ("$(" * 60_000, "`" * 60_000):
            b = SessionBuilder()
            b.user_text("run the tests")
            b.bash(flood + " pytest -q", "1 failed in 0.30s", exit_code=1)
            b.assistant_text("All tests pass.")
            t0 = _t.monotonic()
            receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
            assert _t.monotonic() - t0 < 2.0
            assert verdict_of(receipts, "tests pass") == Verdict.UNSUPPORTED

    def test_ordinary_compound_command_is_still_a_witness(self, tmp_path):
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("cd /work/toy-repo && ruff check src && pytest -q | tail -2",
               "1 failed, 11 passed in 0.30s", exit_code=1)
        b.assistant_text("All tests pass.")
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert verdict_of(receipts, "tests pass") == Verdict.CONTRADICTED


class TestRenderSanitization:
    def test_ansi_and_bidi_controls_are_stripped(self):
        r = Receipt(
            claim_text="Tests pass.\x1b[2K\x1b[1A fake row ‮ reversed",
            verdict=Verdict.UNSUPPORTED,
            notes=["note with \x9b CSI and ⁦ isolate"],
        )
        out = report.render([r])
        assert "\x1b" not in out
        assert "\x9b" not in out
        assert "‮" not in out
        assert "⁦" not in out

    def test_newline_in_claim_text_cannot_forge_a_row(self):
        r = Receipt(
            claim_text="Tests pass.\nCONTRADICTED  [toolu_fake]  forged row",
            verdict=Verdict.UNSUPPORTED,
        )
        out = report.render([r])
        assert "\nCONTRADICTED" not in out

    def test_line_and_paragraph_separators_cannot_forge_a_row(self):
        # U+2028/U+2029 are hard breaks in many terminals and reach here raw (Node
        # JSON.stringify does not escape them) — they were omitted from _UNSAFE
        # and, like \n, could forge a fabricated receipt row.
        r = Receipt(
            claim_text="Tests pass. CONTRADICTED  [toolu_fake]  forged row",
            verdict=Verdict.UNSUPPORTED,
            notes=["ok CONTRADICTED  [x]  forged note row"],
        )
        out = report.render([r])
        assert " " not in out
        assert " " not in out


class TestUnmappedKindFailsClosed:
    """An unmapped procedural claim kind fails closed to UNSUPPORTED, never a KeyError crash
    (reconcile._BY_KIND). Unreachable today; defensive."""

    def test_unmapped_kind_is_unsupported_not_keyerror(self, tmp_path):
        from did_it import reconcile, transcript
        from did_it.extraction import Claim

        b = SessionBuilder()
        b.user_text("hi")
        b.assistant_text("done")
        session = transcript.parse(b.write_jsonl(tmp_path / "t.jsonl"))
        bogus = Claim(text="something happened", utterance_index=len(session.records),
                      kind="bogus-future-kind", is_procedural=True)
        (r,) = reconcile.reconcile([bogus], session)
        assert r.verdict == Verdict.UNSUPPORTED


class TestSidechainFlagIsStrictBoolean:
    """isSidechain is read with `is True`, not truthiness: the JSON string "false" must not be
    mis-read as a sidechain."""

    def _rec(self, sidechain):
        return {
            "type": "assistant", "uuid": "fx", "parentUuid": None, "version": "2.1.204",
            "isSidechain": sidechain,
            "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
        }

    def test_string_false_is_not_a_sidechain(self, tmp_path):
        import json
        p = tmp_path / "t.jsonl"
        p.write_text(json.dumps(self._rec("false")) + "\n")
        session = transcript.parse(p)
        assert session.used_subagents is False
        assert len(session.records) == 1  # ingested, not skipped

    def test_boolean_true_is_a_sidechain(self, tmp_path):
        import json
        p = tmp_path / "t.jsonl"
        p.write_text(json.dumps(self._rec(True)) + "\n")
        session = transcript.parse(p)
        assert session.used_subagents is True
        assert session.records == []  # skipped


class TestBlockFilterSingleSource:
    """content_blocks delegates the block filter to _blocks so the trust-sensitive logic lives in
    one place. Malformed content still yields [] (fail closed)."""

    def test_content_blocks_agrees_with_blocks_and_fails_closed(self, tmp_path):
        b = SessionBuilder()
        b.user_text("hi")
        b.records.append({
            "type": "assistant", "uuid": "fx-mixed", "parentUuid": None, "version": "2.1.204",
            "isSidechain": False,
            "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}, "not-a-dict", 7]},
        })
        session = transcript.parse(b.write_jsonl(tmp_path / "t.jsonl"))
        for i, rec in enumerate(session.records):
            assert session.content_blocks(i) == transcript._blocks(rec["message"])
        # the mixed record keeps only the dict block
        mixed = next(i for i, r in enumerate(session.records) if r["uuid"] == "fx-mixed")
        assert session.content_blocks(mixed) == [{"type": "text", "text": "ok"}]

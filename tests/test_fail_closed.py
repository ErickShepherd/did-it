"""Fail-closed hardening — pins from the 2026-07-10 panel review (C3, C4, C5, C6).

The exit-code contract reserves 1 for CONTRADICTED. Any crash that escapes the pipeline
exits 1 too, so an exit-code consumer reads a byte-corrupt file as an accusation (C3/C4).
A quadratic regex on untrusted output hangs the Stop hook (C5). Untrusted prose flows raw
into the receipt table, so ANSI/bidi controls can visually rewrite it (C6).
"""

from __future__ import annotations

import time
from pathlib import Path

import did_it
from did_it import cli, hook, report
from did_it.testing import SessionBuilder
from did_it.verdicts import Receipt, Verdict


def verdict_of(receipts, fragment):
    (r,) = [x for x in receipts if fragment in x.claim_text]
    return r.verdict


# --- C3: non-UTF-8 bytes must be NOT-EVALUABLE, never exit 1 ---------------------------


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


# --- C4: malformed block internals must not crash build_index --------------------------


class TestJsonLegalSeparators:
    def test_unicode_line_separator_in_prose_does_not_kill_the_session(self, tmp_path):
        # U+2028/U+2029/NEL are legal UNESCAPED inside JSON strings and appear in real
        # tool output; splitting on them fragments a valid line and silently turns the
        # whole session NOT-EVALUABLE — masking every genuine verdict (review round 1).
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


# --- C5: summary scanning must stay linear on adversarial output -----------------------


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
        # Review round 2: a genuine green summary followed by >256KB of echoed log with a
        # stale FAILED line and a red compound tail must stay green — a scan cap that
        # drops the summary re-opens the C2 false accusation it exists to prevent.
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


# --- C6: receipt rendering must neutralize terminal-control content --------------------


class TestPathologicalCommands:
    def test_heredoc_opener_flood_adjudicates_quickly_and_abstains(self, tmp_path):
        # The HEREDOC-stripping regex is quadratic on unterminated openers (review round 3:
        # 15.5s at 160KB). An un-strippable command is not evaluable as a witness at all —
        # no run, no accusation, pure abstention.
        b = SessionBuilder()
        b.user_text("run the tests")
        b.bash("pytest " + "<<X " * 40_000, "1 failed in 0.30s", exit_code=1)
        b.assistant_text("All tests pass.")
        t0 = time.monotonic()
        receipts = did_it.check(b.write_jsonl(tmp_path / "t.jsonl"))
        assert time.monotonic() - t0 < 2.0
        assert verdict_of(receipts, "tests pass") == Verdict.UNSUPPORTED


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

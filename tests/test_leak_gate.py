"""The leak-gate is real infra (design doc D8), so it gets real tests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import leak_gate  # noqa: E402


def test_clean_fixture_passes(tmp_path):
    f = tmp_path / "ok.jsonl"
    f.write_text('{"note": "FIXTURES_ONLY toy repo", "cmd": "pytest -q"}\n')
    assert leak_gate.scan(f) == []


def test_private_path_is_flagged(tmp_path):
    f = tmp_path / "bad.txt"
    f.write_text("/home/user/secret/thing")
    assert leak_gate.scan(f)


def test_fixture_missing_marker_is_flagged(tmp_path):
    d = tmp_path / "fixtures"
    d.mkdir()
    f = d / "nomarker.jsonl"
    f.write_text('{"cmd": "pytest"}\n')
    assert any("marker" in p for p in leak_gate.scan(f))


class TestKnownRepoNamesMechanism:
    """The gitignored owner-supplied 'known repo names' denylist mechanism (audit 2026-07-10,
    the DECIDE fork). The loop provides the MECHANISM; the owner supplies the NAMES. These tests
    exercise the mechanism with a temp names file — they never reference a real private name.
    """

    def test_absent_names_file_is_a_noop(self, tmp_path):
        assert leak_gate.load_local_name_patterns(tmp_path / "does-not-exist.local") == []

    def test_names_file_parsing_skips_blanks_and_comments(self, tmp_path):
        names = tmp_path / ".leakgate-names.local"
        names.write_text("# a comment\n\nAcmeSecretProj\n  spaced-repo  \n")
        pats = leak_gate.load_local_name_patterns(names)
        assert [p.pattern for p in pats] == ["AcmeSecretProj", "spaced\\-repo"]

    def test_supplied_name_flags_a_fixture_case_insensitively(self, tmp_path):
        names = tmp_path / ".leakgate-names.local"
        names.write_text("AcmeSecretProj\n")
        extra = leak_gate.load_local_name_patterns(names)
        f = tmp_path / "ok.jsonl"
        f.write_text('{"note": "FIXTURES_ONLY", "repo": "acmesecretproj/api"}\n')
        assert leak_gate.scan(f) == []                    # clean without the names denylist
        assert any("deny pattern" in p for p in leak_gate.scan(f, extra))  # flagged with it

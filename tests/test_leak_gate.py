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
    f.write_text("/home/alice/secret/thing")
    assert leak_gate.scan(f)


def test_json_form_secret_is_flagged(tmp_path):
    """The JSON/JSONL form `"token": "abc"` — the exact shape every fixture uses — must trip the
    secret regex; the closing quote after the keyword previously blocked the `\\s*[:=]` match."""
    for line in (
        '{"token": "abc123"}',
        '{"api_key": "xyz"}',
        '{"password": "hunter2"}',
        '{"secret" : "s3cr3t"}',
    ):
        f = tmp_path / "leak.txt"
        f.write_text(line)
        assert any("deny pattern" in p for p in leak_gate.scan(f)), line


def test_high_entropy_token_shapes_are_flagged(tmp_path):
    """Beyond AKIA + keyword-colon, the gate must catch the common concrete secret shapes:
    PEM private keys, GitHub tokens, Slack tokens, Google API keys, and AWS-temp keys. Each is a
    near-zero-FP fixed prefix, so a match is a real leak."""
    for secret in (
        "-----BEGIN RSA PRIVATE KEY-----",
        "-----BEGIN PRIVATE KEY-----",
        "ghp_" + "a" * 36,
        "github_pat_" + "A1b2C3d4E5" * 5,
        "xoxb-1234567890-abcdefABCDEF",
        "xoxp-0987654321-ZYXwvu",
        "AIza" + "aB3-_dEf" * 4 + "aBc",  # AIza + 35 chars
        "ASIA" + "1234567890ABCDEF",
    ):
        f = tmp_path / "leak.txt"
        f.write_text(secret)
        assert any("deny pattern" in p for p in leak_gate.scan(f)), secret


def test_fixture_missing_marker_is_flagged(tmp_path):
    d = tmp_path / "fixtures"
    d.mkdir()
    f = d / "nomarker.jsonl"
    f.write_text('{"cmd": "pytest"}\n')
    assert any("marker" in p for p in leak_gate.scan(f))


class TestMarkerEnforcedForAllFixtureFiles:
    """The FIXTURES_ONLY marker is required on EVERY committed file under fixtures/, not just
    .json/.jsonl — a .log/.txt/extensionless fixture was silently exempt."""

    def test_non_json_fixture_without_marker_is_flagged(self, tmp_path):
        d = tmp_path / "fixtures"
        d.mkdir()
        for name in ("data.log", "notes.txt", "extensionless"):
            f = d / name
            f.write_text("toy fixture content, no marker here")
            assert any("marker" in p for p in leak_gate.scan(f)), name

    def test_non_json_fixture_with_marker_passes(self, tmp_path):
        d = tmp_path / "fixtures"
        d.mkdir()
        f = d / "data.log"
        f.write_text("FIXTURES_ONLY toy content")
        assert leak_gate.scan(f) == []

    def test_non_fixture_file_needs_no_marker(self, tmp_path):
        f = tmp_path / "src.log"
        f.write_text("ordinary file, not under fixtures/")
        assert leak_gate.scan(f) == []

    def test_deny_is_global_marker_is_fixtures_scoped(self, tmp_path):
        """Pin the module docstring's two-tier contract: DENY patterns apply to EVERY scanned
        path (inside or outside fixtures/), while the FIXTURES_ONLY marker is required ONLY for
        files under fixtures/. Guards against a future 'broaden the rule' that would wrongly
        demand the marker on eval material / source outside fixtures/."""
        # DENY is global: a private path is flagged even outside fixtures/.
        outside_secret = tmp_path / "eval" / "snapshot.jsonl"
        outside_secret.parent.mkdir()
        outside_secret.write_text('{"path": "/home/alice/secret"}')
        assert any("deny pattern" in p for p in leak_gate.scan(outside_secret))
        # Marker is fixtures-scoped: a markerless, secret-free file OUTSIDE fixtures/ is clean...
        outside_clean = tmp_path / "eval" / "clean.jsonl"
        outside_clean.write_text('{"note": "ordinary eval material, no marker"}')
        assert leak_gate.scan(outside_clean) == []
        # ...but the SAME content UNDER fixtures/ demands the marker.
        d = tmp_path / "fixtures"
        d.mkdir()
        inside = d / "clean.jsonl"
        inside.write_text('{"note": "ordinary eval material, no marker"}')
        assert any("marker" in p for p in leak_gate.scan(inside))


class TestKnownRepoNamesMechanism:
    """The gitignored owner-supplied 'known repo names' denylist mechanism: the tool provides
    the MECHANISM; the owner supplies the NAMES. These tests exercise the mechanism with a temp
    names file — they never reference a real private name.
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

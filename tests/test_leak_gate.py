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

from pathlib import Path

from scripts import release_check


ROOT = Path(__file__).resolve().parents[1]


def test_repository_release_metadata_is_consistent():
    version, errors = release_check.validate(ROOT, tag="v0.2.0")
    assert version == "0.2.0"
    assert errors == []


def test_release_check_rejects_wrong_tag():
    _version, errors = release_check.validate(ROOT, tag="v9.9.9")
    assert errors == ["tag mismatch: expected v0.2.0, got v9.9.9"]

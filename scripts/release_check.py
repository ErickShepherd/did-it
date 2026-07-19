#!/usr/bin/env python3
"""Fail-closed release metadata and tag consistency check."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def _capture(path: Path, pattern: str, label: str) -> str:
    text = path.read_text(encoding="utf-8")
    matches = re.findall(pattern, text, flags=re.MULTILINE)
    if len(matches) != 1:
        raise ValueError(f"{label}: expected exactly one version in {path}, found {len(matches)}")
    return matches[0]


def versions(root: Path) -> dict[str, str]:
    """Read every release-owned version field without third-party parsers."""
    return {
        "pyproject": _capture(
            root / "pyproject.toml",
            r'^version = "([0-9]+\.[0-9]+\.[0-9]+)"',
            "pyproject",
        ),
        "package": _capture(
            root / "src" / "did_it" / "__init__.py",
            r'^__version__ = "([0-9]+\.[0-9]+\.[0-9]+)"',
            "package",
        ),
        "citation": _capture(
            root / "CITATION.cff",
            r'^version: "([0-9]+\.[0-9]+\.[0-9]+)"',
            "citation",
        ),
        "design": _capture(
            root / "docs" / "design" / "did-it.md",
            r"Package version `([0-9]+\.[0-9]+\.[0-9]+)`",
            "design",
        ),
    }


def validate(root: Path, tag: str | None = None) -> tuple[str, list[str]]:
    found = versions(root)
    version = found["pyproject"]
    errors = [f"version mismatch: {found}" for value in found.values() if value != version]
    if errors:
        errors = errors[:1]

    if tag is not None and tag != f"v{version}":
        errors.append(f"tag mismatch: expected v{version}, got {tag}")

    if f"## [{version}]" not in (root / "CHANGELOG.md").read_text(encoding="utf-8"):
        errors.append(f"CHANGELOG.md has no [{version}] release section")
    if not (root / "docs" / "releases" / f"v{version}.md").is_file():
        errors.append(f"missing docs/releases/v{version}.md")
    return version, errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", help="require an exact v<package-version> release tag")
    parser.add_argument("--print-version", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    try:
        version, errors = validate(root, tag=args.tag)
    except (OSError, ValueError) as exc:
        print(f"release-check FAIL: {exc}")
        return 1
    if errors:
        for error in errors:
            print(f"release-check FAIL: {error}")
        return 1
    if args.print_version:
        print(version)
    else:
        print(f"release-check OK: v{version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

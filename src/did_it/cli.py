"""Command-line entry point (skeleton).

    did-it <transcript.jsonl> [--verify <repo>]

Design: docs/design/did-it.md — "Observable contract". The argument surface is wired here; the
pipeline it drives is not implemented. Running it today prints a not-implemented notice and exits 2.
"""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="did-it", description=__doc__.splitlines()[0])
    p.add_argument("transcript", nargs="?", help="path to a Claude Code transcript (.jsonl)")
    p.add_argument(
        "--verify",
        metavar="REPO",
        default=None,
        help="(v1.1) re-execute to upgrade in-transcript BACKED to BACKED-verified",
    )
    p.add_argument("--version", action="store_true", help="print version and exit")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.version:
        from . import __version__

        print(f"did-it {__version__}")
        return 0
    if not args.transcript:
        build_parser().error("the transcript argument is required")
    # Scaffolding: the pipeline (parse -> extract -> reconcile -> report) is not implemented yet.
    print("did-it: not implemented yet — this is scaffolding. See docs/design/did-it.md.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Command-line entry point.

    did-it <transcript.jsonl> [--verify <repo>]

Design: docs/design/did-it.md — "Observable contract". Exit codes: 0 = no accusation (including
abstentions), 1 = at least one CONTRADICTED claim, 2 = usage/IO error.
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
        help="re-execute validated test commands in REPO to upgrade BACKED-transcript "
             "to BACKED-verified (opt-in; runs pure test-runner invocations only)",
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

    import os

    import did_it

    from . import report

    if args.verify is not None and not os.path.isdir(args.verify):
        print(f"did-it: --verify REPO is not a directory: {args.verify}", file=sys.stderr)
        return 2
    if args.verify:
        print(f"did-it: --verify re-executing validated test commands in {args.verify}", file=sys.stderr)
    try:
        receipts = did_it.check(args.transcript, verify_repo=args.verify)
    except OSError as e:
        print(f"did-it: cannot read transcript: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 — exit 1 is reserved for CONTRADICTED
        print(f"did-it: internal error: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    print(report.render(receipts), end="")
    return report.exit_code(receipts)


if __name__ == "__main__":
    raise SystemExit(main())

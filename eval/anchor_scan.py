"""Run the pipeline read-only over local real transcripts and report AGGREGATES.

This is the calibration instrument for the real execution-labeled anchor (design D7):
it prints verdict mixes and extraction diagnostics so bars can be set against reality.
It reads private transcripts in ~/.claude/projects but never copies content anywhere —
run locally; only aggregate numbers may be published.

    .venv/bin/python -m eval.anchor_scan [N] [--samples] [--misses]

  N          number of most-recently-modified transcripts to scan (default 50)
  --samples  print extracted (kind, verdict, claim) rows for manual precision labeling
  --misses   print sentences containing claim-ish words that extraction did NOT gate
             (manual recall labeling: which of these are real procedural claims?)
"""

from __future__ import annotations

import glob
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import did_it  # noqa: E402
from did_it import extraction, transcript  # noqa: E402
from did_it.verdicts import Verdict  # noqa: E402

CLAIMISH = ("pass", "fail", "green", "fixed", "created", "ran ", "clean", "works", "done")

INFORMATIVE = {Verdict.BACKED_TRANSCRIPT, Verdict.BACKED_VERIFIED, Verdict.CONTRADICTED}

#: --samples/--misses emit VERBATIM excerpts of real private sessions. They print only behind an
#: explicit acknowledgment flag (so a redirect/paste can't leak content by accident) AND under a
#: loud banner (design D7: aggregates may be published, content never leaves the machine).
ACK_FLAG = "--print-verbatim-content"
_LOCAL_ONLY_BANNER = (
    "=" * 74 + "\n"
    "  LOCAL-ONLY  ·  VERBATIM PRIVATE SESSION CONTENT BELOW\n"
    "  Do NOT redirect, pipe, paste, commit, or share this output (design D7).\n"
    + "=" * 74
)


def main(argv: list[str]) -> int:
    n = next((int(a) for a in argv if a.isdigit()), 50)
    show_samples = "--samples" in argv
    show_misses = "--misses" in argv
    if (show_samples or show_misses) and ACK_FLAG not in argv:
        print(
            f"REFUSED: --samples/--misses print VERBATIM excerpts of real private sessions.\n"
            f"Re-run locally with {ACK_FLAG} to acknowledge this is local-only output that must\n"
            f"never be redirected, piped, pasted, committed, or shared (design D7). Aggregates\n"
            f"(the numbers below) are safe to publish; the excerpts are not.",
            file=sys.stderr,
        )
        show_samples = show_misses = False

    files = sorted(
        glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")),
        key=lambda p: -os.path.getmtime(p),
    )[:n]

    verdicts: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    sessions = parsed = with_claims = contradicted_sessions = 0
    samples: list[tuple[str, str]] = []
    misses: list[str] = []

    for fp in files:
        sessions += 1
        try:
            session = transcript.parse(fp)
        except (transcript.UnknownSchema, transcript.ParseFailure):
            verdicts["(session NOT-EVALUABLE)"] += 1
            continue
        parsed += 1
        receipts = did_it.check(fp)
        claims = extraction.extract_claims(session)
        for c in claims:
            kinds[c.kind or "?"] += 1
        if receipts:
            with_claims += 1
        if any(r.verdict is Verdict.CONTRADICTED for r in receipts):
            contradicted_sessions += 1
        for r in receipts:
            verdicts[r.verdict.value] += 1
            if show_samples and len(samples) < 60:
                samples.append((r.verdict.value, r.claim_text[:110]))
        if show_misses and len(misses) < 60:
            gated = {c.text for c in claims}
            for idx, rec in enumerate(session.records):
                if rec.get("type") != "assistant":
                    continue
                for block in session.content_blocks(idx):
                    if block.get("type") != "text":
                        continue
                    for sent in extraction.sentences(block.get("text") or ""):
                        low = sent.lower()
                        if sent not in gated and any(w in low for w in CLAIMISH):
                            misses.append(sent[:110])

    total = sum(v for k, v in verdicts.items() if not k.startswith("("))
    informative = sum(verdicts[v.value] for v in INFORMATIVE)
    print(f"sessions scanned: {sessions}  parsed: {parsed}  with-claims: {with_claims}")
    print(f"sessions with >=1 CONTRADICTED: {contradicted_sessions}")
    print(f"claims: {total}  kinds: {dict(kinds)}")
    print(f"verdicts: {dict(verdicts)}")
    if total:
        print(f"informative-verdict rate: {informative}/{total} = {informative / total:.0%}")
    if show_samples or show_misses:
        print("\n" + _LOCAL_ONLY_BANNER)
    if show_samples:
        print("--- extracted claim samples (verdict · claim) ---")
        for v, text in samples:
            print(f"  {v:<18} {text}")
    if show_misses:
        print("--- claim-ish sentences NOT gated (recall candidates) ---")
        for s in misses[:60]:
            print(f"  {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

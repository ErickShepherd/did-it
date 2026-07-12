"""Schema-range bump instrument — measure what admitting new schema versions WOULD do.

This is the standing tool behind the schema-range validation policy
(docs/design/schema-range-validation.md, SRV3): it mechanizes the SRV2 evidence bar so a
range bump is "run sweep -> bar green -> edit the two constants + fixtures -> commit citing
these aggregates -> review". Sibling of eval/anchor_scan.py; same aggregates-only discipline.

It widens SUPPORTED_SCHEMA_RANGE IN THIS PROCESS ONLY (the repo is untouched) to include the
candidate versions, then runs did_it.check() end-to-end over every local transcript that
carries a candidate-version record. It reads private transcripts in ~/.claude/projects but
never copies, prints, or emits their content (design D7/D8): only the aggregate numbers and a
pass/fail verdict against the bar are printed, and they are safe to publish.

    .venv/bin/python -m eval.schema_sweep 2.1.206 2.1.207

  VERSION...   one or more candidate versions to validate (e.g. 2.1.206 2.1.207). The range is
               widened in-memory to span the current low endpoint through the highest candidate.

Exit code: 0 if every mandatory SRV2 criterion passes; 1 if a criterion fails (a CONTRADICTED, a
crash, a schema-caused NOT-EVALUABLE, an under-volume version, or a missing core block type) —
the bump is NOT cleared to land as written, adjudicate before editing the constants; 2 on a
usage error (no candidate versions given, or an unparseable X.Y.Z version).
"""

from __future__ import annotations

import glob
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import did_it  # noqa: E402
from did_it import transcript  # noqa: E402
from did_it.verdicts import Verdict  # noqa: E402

#: SRV2.2 volume floor — a candidate below either threshold is not yet ready to validate.
MIN_SESSIONS = 10
MIN_RECORDS = 5_000

#: SRV2.4 — the four block types every pipeline stage may consume; all must appear at each
#: candidate version. Other block/record types are enumerated and confirmed unconsumed, not
#: failed (they pass through _blocks untouched — every consumer keys on `type`).
CORE_BLOCK_TYPES = frozenset({"text", "thinking", "tool_use", "tool_result"})
KNOWN_BLOCK_TYPES = CORE_BLOCK_TYPES | {"image", "fallback"}
KNOWN_RECORD_TYPES = frozenset({"assistant", "user", "attachment", "system"})

#: SRV2.3 classifies only SESSION-LEVEL NOT-EVALUABLE receipts — those check() emits with
#: claim_text == _SESSION_LEVEL_CLAIM (an unknown schema, a parse failure, or any other parse-
#: stage crash caught by its top-level backstops in did_it/__init__.py). Under the widened range
#: a session-level NE is always a bar violation, of two kinds: an expected schema/parse cause
#: (UnknownSchema — an out-of-range record still in a mixed-version file — or ParseFailure — a
#: corrupt/oversize line), or ANY OTHER cause, which is a backstop MASKING an internal crash and
#: must fail the bar (SRV2.3c) so a real crash is never silently green-lit.
#:
#: PER-CLAIM NOT-EVALUABLE receipts (reconcile._absent's "un-ingested sidechain (v1.1)" note, a
#: normal outcome when a subagent session has an unbacked claim) carry the real claim text, NOT
#: the sentinel — they are a v1 limitation, not a schema signal, and are excluded from the bar.
_SESSION_LEVEL_CLAIM = "(entire session)"  # mirrors did_it/__init__.py's _not_evaluable receipt
_SCHEMA_CAUSES = frozenset({"UnknownSchema", "ParseFailure"})


def _crash_summary(e: Exception) -> str:
    """Path-free one-line label for a library-boundary crash. check() re-raises OSError
    (missing/unreadable file) whose str() carries the full private ~/.claude/projects/<repo>/…
    path — so record only the type and, for OSError, its errno + the basename, never the raw
    message (design D7/D8, SYS-3). The basename is the session file (a UUID), not the private
    repo path.
    """
    if isinstance(e, OSError):
        base = os.path.basename(e.filename) if e.filename else "?"
        return f"{type(e).__name__}(errno={e.errno}, file={base})"
    return type(e).__name__


def _msg_count(rec_types: Counter[str]) -> int:
    """Records that ARE message records (assistant/user) — the SRV2.2 volume-floor population.
    Ambient versioned records (attachment/system) carry a `version` but are not what the pipeline
    consumes, so they must not pad the floor.
    """
    return sum(rec_types[t] for t in transcript.MESSAGE_TYPES)


def main(argv: list[str]) -> int:
    candidates = [a for a in argv if not a.startswith("-")]
    if not candidates:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        print("usage: python -m eval.schema_sweep VERSION [VERSION ...]", file=sys.stderr)
        return 2
    cand_tuples = {}
    for v in candidates:
        t = transcript._version_tuple(v)
        if t is None:
            print(f"not a valid X.Y.Z version: {v!r}", file=sys.stderr)
            return 2
        cand_tuples[v] = t
    candidate_set = set(candidates)

    # Widen the range in-memory only: keep the current low endpoint, raise the high endpoint to
    # the highest candidate. This measures exactly what the two-constant bump WOULD admit.
    lo, hi = transcript.SUPPORTED_SCHEMA_RANGE
    new_hi = max([hi, *cand_tuples.values()])
    transcript.SUPPORTED_SCHEMA_RANGE = (lo, new_hi)
    print(f"widened range (in-memory): {'.'.join(map(str, lo))} - {'.'.join(map(str, new_hi))}")
    print(f"candidate versions: {', '.join(sorted(candidate_set))}\n")

    files = sorted(glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")))

    # Pass 1 — cheap streaming inventory: per candidate version, which files carry it plus the
    # record/block types that ride on it (rec_types doubles as the message-record count source).
    files_with: dict[str, set[str]] = {v: set() for v in candidate_set}
    rec_types: dict[str, Counter[str]] = {v: Counter() for v in candidate_set}
    block_types: dict[str, Counter[str]] = {v: Counter() for v in candidate_set}
    target_files: set[str] = set()                               # any candidate-version record
    multi_version_files = 0

    for fp in files:
        try:
            if os.path.getsize(fp) > transcript._MAX_TRANSCRIPT_BYTES:
                continue
            vers_here: set[str] = set()
            with open(fp, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"version"' not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(rec, dict):
                        continue
                    v = rec.get("version")
                    if not isinstance(v, str):
                        continue
                    vers_here.add(v)
                    if v in candidate_set:
                        target_files.add(fp)
                        files_with[v].add(fp)
                        rec_types[v][str(rec.get("type"))] += 1
                        m = rec.get("message")
                        if isinstance(m, dict) and isinstance(m.get("content"), list):
                            for b in m["content"]:
                                if isinstance(b, dict):
                                    block_types[v][str(b.get("type"))] += 1
        except OSError:
            continue
        if len(vers_here) > 1:
            multi_version_files += 1

    print(f"transcript files scanned: {len(files)}")
    print(f"files spanning >1 distinct version: {multi_version_files}")
    print(f"files with a candidate-version record: {len(target_files)}\n")

    for v in sorted(candidate_set):
        rec_c, block_c = rec_types[v], block_types[v]
        # `type` strings are attacker-controlled + unbounded; only the KNOWN_* labels (module
        # constants, never transcript-derived) are safe to echo. Unknowns are counted, never
        # labelled — the raw label could smuggle a secret onto publishable stdout (design D7/D8).
        known_recs = {t: rec_c[t] for t in sorted(KNOWN_RECORD_TYPES) if t in rec_c}
        known_blocks = {t: block_c[t] for t in sorted(KNOWN_BLOCK_TYPES) if t in block_c}
        unknown_rec_types = set(rec_c) - KNOWN_RECORD_TYPES
        unknown_block_types = set(block_c) - KNOWN_BLOCK_TYPES
        unknown_rec_n = sum(rec_c[t] for t in unknown_rec_types)
        unknown_block_n = sum(block_c[t] for t in unknown_block_types)
        total_versioned = sum(rec_c.values())
        print(f"[{v}]  sessions: {len(files_with[v])}   message records: {_msg_count(rec_c)}"
              f"   (all versioned records: {total_versioned})")
        print(f"       record types: {known_recs}")
        print(f"       block types:  {known_blocks}")
        if unknown_block_types:
            print(f"       unknown (unconsumed) block types: {len(unknown_block_types)} distinct, "
                  f"{unknown_block_n} records (labels withheld — D7/D8)")
        if unknown_rec_types:
            print(f"       unknown record types: {len(unknown_rec_types)} distinct, "
                  f"{unknown_rec_n} records (labels withheld — D7/D8)")
    print()

    # Pass 2 — end-to-end check() over every file with a candidate-version record (SRV2.1).
    verdicts: Counter[str] = Counter()
    session_ne_causes: Counter[str] = Counter()   # session-level NE only (see _SCHEMA_CAUSES)
    per_claim_ne = 0                                # per-claim NE (sidechain v1 limit) — not a bar signal
    crashes: list[str] = []
    sessions = ok = with_claims = contradicted_sessions = 0

    for fp in sorted(target_files):
        sessions += 1
        try:
            receipts = did_it.check(fp)
        except Exception as e:  # noqa: BLE001 — a raise at the library boundary IS the finding
            crashes.append(_crash_summary(e))
            continue
        ok += 1
        if receipts:
            with_claims += 1
        if any(r.verdict is Verdict.CONTRADICTED for r in receipts):
            contradicted_sessions += 1
        for r in receipts:
            verdicts[r.verdict.value] += 1
            if r.verdict is Verdict.NOT_EVALUABLE:
                if r.claim_text == _SESSION_LEVEL_CLAIM:
                    session_ne_causes[r.notes[0].split(":")[0] if r.notes else "?"] += 1
                else:
                    per_claim_ne += 1  # reconcile._absent sidechain note — expected, off-bar

    print(f"END-TO-END: {sessions} sessions, {ok} check() ok, {with_claims} with >=1 receipt")
    print(f"verdict mix: {dict(verdicts)}")
    print(f"session-level NOT-EVALUABLE causes: {dict(session_ne_causes)}")
    print(f"per-claim NOT-EVALUABLE (un-ingested sidechain, off-bar): {per_claim_ne}")
    print(f"library-boundary crashes: {len(crashes)}")
    for c in crashes[:10]:
        print(f"  {c}")
    print()

    # --- SRV2 bar: pass/fail per mandatory criterion ---------------------------------------
    schema_ne = sum(n for cause, n in session_ne_causes.items() if cause in _SCHEMA_CAUSES)
    masked_ne = sum(n for cause, n in session_ne_causes.items() if cause not in _SCHEMA_CAUSES)

    # SRV2.1 (end-to-end, never parse-only) is a property of the instrument, not a measured
    # outcome — every candidate session above went through did_it.check(), not parse alone. It is
    # stated as a note, not a pass/fail row that can never fail.
    print("SRV2.1  satisfied by construction: candidate sessions run did_it.check() end-to-end.\n")

    checks: list[tuple[bool, str]] = []
    for v in sorted(candidate_set):
        msg = _msg_count(rec_types[v])
        vol_ok = len(files_with[v]) >= MIN_SESSIONS and msg >= MIN_RECORDS
        checks.append((vol_ok, f"SRV2.2  {v}: >={MIN_SESSIONS} sessions ({len(files_with[v])}) "
                               f"and >={MIN_RECORDS} message records ({msg})"))
    checks.append((len(crashes) == 0, f"SRV2.3a library-boundary crashes == 0 ({len(crashes)})"))
    checks.append((schema_ne == 0, f"SRV2.3b schema/parse-caused NOT-EVALUABLE == 0 ({schema_ne})"))
    checks.append((masked_ne == 0, f"SRV2.3c masked internal-crash NOT-EVALUABLE == 0 ({masked_ne})"))
    for v in sorted(candidate_set):
        missing = CORE_BLOCK_TYPES - set(block_types[v])
        checks.append((not missing, f"SRV2.4  {v}: all four core block types present"
                                    + (f" (MISSING {sorted(missing)})" if missing else "")))
    checks.append((contradicted_sessions == 0,
                   f"SRV2.5  CONTRADICTED sessions == 0 ({contradicted_sessions})"))

    print("SRV2 evidence bar:")
    all_pass = True
    for passed, label in checks:
        all_pass = all_pass and passed
        print(f"  [{'PASS' if passed else 'FAIL'}]  {label}")
    print()
    if all_pass:
        print("VERDICT: PASS — the widened range clears the SRV2 bar; cite these aggregates "
              "in the bump commit.")
        return 0
    print("VERDICT: FAIL — do NOT land the bump as written; adjudicate the failing criteria "
          "(a CONTRADICTED needs manual true/false adjudication per SRV2.5).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

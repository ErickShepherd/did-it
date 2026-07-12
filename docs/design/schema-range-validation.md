# Schema-range validation policy — Design

**Status:** ratified 2026-07-11; grounds the 2.1.156–2.1.205 → 2.1.156–2.1.207 bump.
Implementation of the bump itself is a follow-up; this document is the methodology it must follow.
Amends design doc D2 (`docs/design/did-it.md`): "one pinned schema" becomes "a pinned *validated
range*, extendable only under this policy."

## Context / problem

`SUPPORTED_SCHEMA_RANGE` (`src/did_it/transcript.py`) pins the Claude Code schema versions this
build is validated against; any message record outside it fails closed to a session-level
`NOT-EVALUABLE` (`UnknownSchema`). That never-guess gate is the product's core invariant — but the
CLI releases faster than the range moves (2.1.205 → 2.1.207 in days), and while the installed CLI
is ahead of the range, *every* freshly produced transcript is `NOT-EVALUABLE`: Stop hooks, CI
integrations, and library callers are all degraded. Bumping the range is therefore a recurring
maintenance event and needs a standing, evidence-preserving methodology — not an ad-hoc constant
edit each time.

Prior art being generalized: the original range was ratified on a spike showing core fields stable
across 10 versions sampled in 2.1.156–2.1.204 with one parser, plus a separate verification of
2.1.205 (comment at `transcript.py:23-25`).

## Goals & non-goals

**Goals:** a mechanical, repeatable evidence bar for admitting new versions; evidence at least as
strong as the original spike, every time; the fail-closed gate preserved exactly.

**Non-goals:** loosening the gate in any form (no "accept any 2.1.x", no warn-and-continue);
auto-bumping (the constants move only in a human-reviewed commit that records the evidence);
proactive release detection (operator use surfaces a lagging range within days; this policy
optimizes the response, not the detection); schema *migration* — a version whose records change
shape needs code and full re-calibration, not a range edit (see SRV4).

## Evidence — the 2026-07-11 sweep behind the 2.1.207 bump

End-to-end `did_it.check()` (parse → extract → reconcile), with the range widened in-memory to
2.1.207, over every transcript in the operator's local store (`~/.claude/projects`) containing
candidate-version records. Aggregates only, per D7/D8 — no session content leaves the machine.

- **Corpus:** 3,636 transcript files scanned; **206 sessions** contain 2.1.206/2.1.207 message
  records (189 with 2.1.206, 20 with 2.1.207) — **16,706** message records at 2.1.206 and
  **14,662** at 2.1.207. 62 files span multiple versions (sessions survive CLI upgrades),
  confirming the per-record — not per-file — gate is the right frame.
- **Pipeline:** 206/206 sessions returned receipts with **zero library-boundary crashes** and
  **zero** `UnknownSchema`/`ParseFailure`-caused `NOT-EVALUABLE`.
- **Calibration:** **0 `CONTRADICTED` across all 206 sessions** — the anchor's zero-accusation
  result extends to the new versions on the same honest-session population. Verdict mix
  (1,008 `NOT-CHECKABLE` / 912 `UNSUPPORTED` / 377 `BACKED-transcript`) is consistent with the
  existing anchor's shape.
- **Shape:** versioned records at 2.1.206/2.1.207 are types `assistant`/`user`/`attachment`/
  `system`; all four core block types (`text`/`thinking`/`tool_use`/`tool_result`) are richly
  present, plus `image` and `fallback` blocks, which no pipeline stage consumes (ignored by
  construction — `_blocks` passes them through and every consumer keys on `type`). Ambient record
  types (`queue-operation`, `ai-title`, `file-history-snapshot`, …) carry no `version` field and
  are filtered by `MESSAGE_TYPES` *before* the version gate, so they can never trip it.

## Key decisions

- **SRV1 — Bump the range to 2.1.156–2.1.207.** Both new versions are directly validated (no
  interpolated gap in this bump). Two constants move together: `SUPPORTED_SCHEMA_RANGE` and the
  scaffold-compat `SUPPORTED_SCHEMA_VERSIONS` endpoints tuple. The gate logic itself is untouched.
- **SRV2 — Evidence bar for any bump** (all mandatory; aggregates recorded in the bump commit):
  1. **End-to-end, never parse-only:** the sweep runs `did_it.check()` over every locally
     available session containing candidate-version message records.
  2. **Volume floor:** ≥ 10 sessions **and** ≥ 5,000 message records at each candidate version
     (2.1.207 cleared this within days of release; a version that can't is not yet ready to
     validate).
  3. **Zero tolerance:** no library-boundary crash; no `UnknownSchema`/`ParseFailure`-caused
     `NOT-EVALUABLE` under the candidate range.
  4. **Shape coverage:** all four core block types observed at the candidate version; any block
     or record type outside the known set is enumerated and confirmed unconsumed (ignored), not
     silently half-read.
  5. **Accusation check:** 0 `CONTRADICTED` across the swept sessions; any accusation is manually
     adjudicated as true-or-false *before* the bump lands (a true accusation is fine; a false one
     stops the bump — it is a parser/reconciler bug, not a range problem).
  6. **Gaps:** contiguous-range interpolation between directly-validated versions is accepted
     (precedent: the original range; several intra-range versions were never observed locally).
     Unvalidated versions *above* the top endpoint are never included.
- **SRV3 — Standing instrument: a committed sweep script + this runbook, not CI.**
  `eval/schema_sweep.py` (stdlib-only, sibling of `eval/anchor_scan.py`, same aggregates-only
  output discipline) mechanizes SRV2 end to end: inventory local versions, run the widened-range
  sweep, print pass/fail against the bar. A bump then is: run sweep → bar green → edit the two
  constants + fixtures → commit citing the aggregates → review.
  **Rejected — CI canary:** CI has neither real transcripts (D8: never committed) nor the
  operator's installed CLI; a canary could only re-test synthetic fixtures the test suite already
  covers, asserting nothing about real schema drift. **Rejected — runbook prose only:** the
  procedure is ~100 lines and entirely mechanical; leaving it unscripted invites methodology drift
  between bumps. **Rejected — auto-bump:** the never-guess gate moves only by deliberate,
  reviewed human action.
- **SRV4 — Calibration transfer.** A constants-only bump changes no parsing, extraction, or
  reconciliation logic, so behavior on already-validated versions is identical by construction —
  the historical zero-false-accusation anchor (0/400) needs no re-run for old versions. The
  new-version accusation check (SRV2.5) is the anchor's extension to the new population; the
  sweep above supplies it for 2.1.206/2.1.207 (0/206). **Rule:** if a bump requires *any* code
  change beyond the two constants and fixtures, it is a schema migration — full anchor re-scan
  (≥ 200 sessions) before merging.
- **SRV5 — Fixture policy.** Committed fixtures stay synthetic (D8). The version-gate tests in
  `tests/test_fail_closed.py` are parametrized over both range endpoints plus one-below and
  one-above (both → `UnknownSchema`), pinning the gate's edges on both sides. A consistency test
  asserts `SUPPORTED_SCHEMA_VERSIONS` renders exactly the endpoints of `SUPPORTED_SCHEMA_RANGE`
  (the two constants cannot drift apart). The `SessionBuilder` default version stays a mid-range
  value; no broad test sweep.

## Alternatives considered

- **Validate 2.1.207 only, leave 2.1.206 a gap** — pointless: 2.1.206 has 9× the local session
  count and validates for free in the same sweep; a directly-validated version always beats an
  interpolated one.
- **Per-file version gate instead of per-record** — rejected: 62 real files span multiple
  versions; a file-level gate would either miss out-of-range records or reject mixed files that
  are fine.
- **Warn-and-parse on unknown versions ("optimistic mode")** — rejected outright: it converts the
  never-guess invariant into a default-guess, and one silently mis-parsed schema is the
  mass-false-verdict failure the risk register names.
- **CI canary / release-watcher** — rejected in SRV3 (nothing real to test in CI; detection is not
  the bottleneck).

## Risks

- **The evidence corpus is one operator's distribution** — same limitation as the anchor (D7);
  acceptable for a schema-shape claim (schema varies by CLI version, not by user), and the volume
  floor keeps it from thinning.
- **A future version changes record shape without breaking parse** (fields renamed, semantics
  shifted) — a sweep would pass while meaning drifts. Mitigated by SRV2.4's enumeration step and
  fail-closed defaults downstream; residual risk accepted as intra-major, consistent with the
  design doc's drift posture.
- **Sweep script rots between bumps** — low: stdlib-only, no fixtures, exercised at every bump;
  same maintenance class as `anchor_scan.py`.

## Rollout (the follow-up implementation)

1. `eval/schema_sweep.py` per SRV3.
2. Constants bump per SRV1 + fixture/test changes per SRV5 (the bump commit cites the sweep
   aggregates, re-run at merge time).
3. Amend `transcript.py`'s range comment to cite this document.

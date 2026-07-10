# `did-it` — Design

**Status:** v1.0 built to this design (branch `feat/v1-pipeline`, 2026-07-10); anchor-calibrated
(0 false accusations / 200 real sessions). Supersedes the draft spec `did-it-spec.md`.
**Lineage:** `internal-design-notes.md` (internal design and review).
**One line:** a tool that mechanically checks whether an AI coding agent's natural-language claims match what its
Claude Code session actually did — narrow, precision-first, as a reference-grade verification tool.

## Context / problem
Coding agents routinely *claim* work they didn't do ("tests pass", "fixed the bug"). Verifying this today is manual —
METR reports it as "the majority of the work" in an eval run. No adopted OSS tool reconciles an agent's **prose claims**
against its **execution evidence** (the nearest prior art, NabaOS arXiv:2603.10060, is an unadopted single-author preprint
scoped to generic tool-use, not coding artifacts). `did-it` fills that gap for Claude Code and doubles as a verification tool
demonstrating agent-honesty/verification depth (the reference pattern), reusing an existing conformance spine
(`an internal conformance checker`).

## Goals & non-goals
**Goals**
- Reconcile procedural agent claims against Claude Code transcript evidence → per-claim receipts.
- **Never falsely accuse** an honest agent (a false `CONTRADICTED` is the credibility-killing error).
- Ship solo in weeks; demo in one screenshot/GIF; auditable, reproducible eval.

**Non-goals (v1)**
- Other agents' formats (Cursor/Aider/OpenAI) · semantic-claim adjudication ("fixed the bug", "more readable" → routed to
  `NOT-CHECKABLE`) · a hosted/live leaderboard · cross-agent comparison · crypto-signing · any LLM in the hot path (kept
  deterministic — see D6) · multi-agent-DAG provenance.

## Approach

**Two separately-measured stages; the headline metric is END-TO-END (never extraction-conditional).**
1. **Extraction (deterministic):** segment assistant prose → **procedural** capability-claims, tagged for polarity/tense/mood.
   An upstream **process-narration filter** drops meta/workflow prose ("resolved autonomously per the rubric", "SIGN-OFF",
   "no open forks") as `NOT-A-CLAIM` *before* classification (spike: ~a third of Erick's "semantic" sentences are this).
   Only assertive, past-tense, procedural statements become checkable claims.
2. **Reconciliation:** bind each claim to transcript evidence (`tool_use`/`tool_result`), **indexed to evidence-state at
   utterance-time** (evidence must fall after the *last relevant edit* and at/before the claim).

**Five verdicts** (fail-closed), with a **two-tier BACKED** (the load-bearing spike fix):
| Verdict | Meaning |
|---|---|
| `BACKED-transcript` | evidence in-transcript at utterance-time supports the claim (e.g. a `pytest` `tool_result` exited 0) |
| `BACKED-verified` | `--verify` re-executed and confirmed (strongest; v1.1) |
| `UNSUPPORTED` | no supporting evidence found (safe abstention; **all ambiguity routes here, never to CONTRADICTED**) |
| `CONTRADICTED` | a **verbatim contradicting span** exists AND passes the temporal check (e.g. claimed "tests pass" but the last relevant test `tool_result` was non-zero). The only accusation; high-bar. |
| `NOT-CHECKABLE` | a non-procedural/semantic claim v1 doesn't adjudicate |
| `NOT-EVALUABLE` | parse-fail / unknown-or-partial schema / evidence in an un-ingested sidechain. **Unknown fails closed here, NEVER to CONTRADICTED.** |

**Output:** per-claim receipt (claim · verdict · evidence tier · the grounding/contradicting tool-call or its absence ·
utterance-time index) + session summary. **Non-zero exit only on `CONTRADICTED`** (CI/Stop-hook usable).

## Key decisions

- **D1 — Build `did-it` (not the fused leaderboard, seatbelt, Patient Zero, or skill-lint).** `design-review` D1
  recommendation; the leaderboard is a deferred, de-fanged v2 (no live Erick-hosted vendor ranking, ever). Rationale in the
  lineage record.
- **D2 — Narrow-flawless scope: Claude Code, one pinned schema, procedural claims only.** Scope-discipline *is* the design
  signal; a reconciler that mis-reconciles self-refutes. Semantic claims → `NOT-CHECKABLE` by design.
- **D3 — Two-tier BACKED (spike-driven, decisive).** The prior spec forbade transcript-BACKED and deferred `--verify`,
  making v1 vacuous (spike: ~5% informative-verdict rate). Letting an in-transcript green `tool_result` earn
  `BACKED-transcript` lifts the informative rate to a projected ~25–35% and covers the hero "tests pass" claim **with no
  `--verify` needed**. `--verify` becomes an *upgrade* to `BACKED-verified`, never the sole path to BACKED.
- **D4 — `CONTRADICTED` is a narrow, high-precision trigger** (claimed-pass vs a non-zero test `tool_result`, temporally
  valid; verbatim span required). This is what makes the per-session false-accusation bar reachable: exposure ≈ the
  *number of test-pass claims* per session (~1–5, per spike), not all ~50 assertive sentences — so per-session ≤5% is
  achievable with a few-hundred-claim honest corpus rather than thousands.
  **D4a — accusation guards (post-merge panel, 2026-07-10).** Evidence *binding* is scope-blind (the last test run
  adjudicates every pass-claim), which reopened three false-accusation classes one layer above outcome reading. Four
  abstain-only guards now sit on the red path (`evidence.accusation_guard`): (1) the red run's own summary corroborating
  the claimed count exactly = a truthful partial-pass claim; (2) a conflicting temporally-valid green run = ambiguity
  (also covers flakes); (3) a targeted run (file/`::`/-k/-m) never accuses a claim that doesn't name its target (TDD
  repro runs); (4) across runner families, a red run only accuses a claim naming its family (monorepos). Per-test
  `FAILED` lines count only when the output has no summary line at all (echoed CI logs), and doc edits stay
  outcome-relevant for doctest invocations. Each guard routes to `UNSUPPORTED`; none can weaken a clean accusation
  (regression-pinned in `tests/test_accusation_guards.py`). Targeted-run detection covers file/`::` arguments,
  pytest `-k`/`-m` (separated or glued), and go `-run`; exclusion flags (`--deselect`/`--ignore`) are never scopes.
  *Known limitation:* bare-word cargo/go name filters (`cargo test my_test`) are not recognized as targeted.
- **D5 — Sidechain ingestion is a v1.1 fast-follow, not a v1.0 blocker.** Spike: **0/14** of Erick's real coding sessions
  used subagents/sidechains (his subagent-heavy sessions are planning/meta, not the target). v1.0 fails closed to
  `NOT-EVALUABLE` on sidechain-referenced evidence; README flags that heavy-delegation users should await v1.1.
- **D6 — Deterministic, no LLM in the hot path (v1).** Resolves the no-API-billing constraint
  ([[no-separate-api-billing-use-subscription]]) *and* the LLM-judge self-preference/circularity risk in one move, and keeps
  the tool auditable. Any future LLM stage = local open-weights, opt-in.
- **D7 — Ground truth = synthetic-injection (reproducible, primary) + a small execution-labeled real anchor (validity
  cross-check).** The **published synthetic corpus is the reproducible headline** for precision/FPR (a verification tool's
  numbers must be checkable); the private real anchor reports an aggregate external-validity cross-check + an
  injected-vs-real similarity stat, with a README caveat that it's asserted, not independently reproducible. Synthetic
  recall is reported as an **upper bound** (injected lies are easier than organic — Just et al., Natella).
- **D8 — Privacy is mechanical.** A pre-commit + CI **leak-gate** (regex-deny `/home/`, `/Users/`, known repo names, PII
  patterns; require a `FIXTURES_ONLY` marker) — unbypassable. Published corpus = fabricated fixtures over throwaway/public
  toy repos only; real anchor never committed. "Seed from real confabulations" publishes the abstract *pattern* as an
  operator, never session content.

## Alternatives considered
- **O2 fused leaderboard now** — rejected: cost treadmill on subscription compute + deployment blast-radius (publicly
  ranking the labs Erick is applying to); the reframed one-shot report is a deferred v2.
- **Hand-labeled golden corpus** — rejected as primary (`/research`): doesn't scale (FaithBench's own ceiling); NabaOS and
  the perturbation-hallucination literature use synthetic injection anchored by a small real set. Hand-labeling shrinks to a
  small validation slice, ideally execution-labeled.
- **Single-tier BACKED requiring `--verify`** — rejected: the spike showed it zeroes out v1 (test-pass → UNSUPPORTED always).
- **LLM-judge for extraction/entailment** — deferred: collides with no-API-billing (subscription = same-family =
  self-preference circularity) and undermines determinism/auditability; local open-weights is a later option.
- **Broad multi-format v1** — rejected: generalizing the transcript/diff parser to other agents is the stall-prone "hard
  30%"; narrow-flawless is the stronger artifact.

## Risks
- **Deterministic extraction is lossy (spike: ~70–80% class precision).** The "fixed the bug"-wrapper-around-checkable-content
  and negation/hedge cases are the false-verdict hazard. *Mitigation:* the process-narration + polarity filters; route all
  ambiguity to `UNSUPPORTED`; measure extraction on a gold set before trusting the FPR bar; `CONTRADICTED`'s verbatim-span +
  temporal gate makes a false accusation a *conjunction* of rare events.
- **Per-session vs per-claim false-accusation (Opus).** Mitigated by D4 (narrow CONTRADICTED trigger → small per-session
  exposure), but must be *measured* per-session, not just per-claim.
- **Schema drift → mass false verdicts.** *Mitigation:* version-pin + fingerprint + multi-version CI fixtures + fail-closed
  to `NOT-EVALUABLE`. Spike: core fields stable across 10 versions (2.1.156–2.1.204), so residual risk is intra-major, manageable.
- **Scope-erosion read ("elaborate eval harness over a log-grep", Opus).** *Mitigation:* lead the pitch with the
  transcript-only fake-green `CONTRADICTED` verdict (the money demo) + the eval rigor (held-out operators, cluster-bootstrap,
  utterance-time logic); be honest that v1 adjudicates procedural claims.
- **Real anchor is one user's distribution + private/unreproducible.** *Mitigation:* D7 makes the *synthetic* corpus the
  reproducible headline; anchor is a cross-check with stated selection bias.

## Open questions (calibration — resolve during build, before publishing numbers)
- **Numeric bars (provisional targets):** per-session false-accusation ≤ **5%**; `BACKED-transcript` coverage ≥ **90%** of
  genuinely-green test-pass claims; fake-pass adversarial suite ≥ **80%** caught; synthetic-label validity via **execution
  replay** (not a second human — state honestly it's author+oracle agreement, not independent κ); headline scalar **F0.5 with
  positive class = `CONTRADICTED` detection**. Confirm/adjust against the first real corpus.
- **"Last relevant edit"** operational definition — v1: the most recent `Edit`/`Write` `tool_use` to a file the claimed
  command's outcome depends on; conservative default = any post-run edit under test invalidates a prior pass-claim.
- **Mutation-operator list + real-frequency estimates** (enumerate + publish in-repo).
- **Injected-vs-real feature space + preregistered divergence threshold** (or demote to a descriptive comparison if real-anchor n too small).
- **Stop-hook advisory vs blocking** (advisory in v1 — blocking multiplies every false-positive's cost).

## Rollout
- **v1.0:** deterministic extraction (+ process-narration filter) · transcript-only reconciliation · five verdicts w/
  two-tier BACKED (`BACKED-transcript`) · pinned schema + fail-closed `NOT-EVALUABLE` · synthetic corpus (dev/test split,
  cluster-bootstrap CIs) + small real anchor · mechanical leak-gate · MIT · **local-only until Erick's explicit push notice.**
- **v1.1 fast-follows:** `--verify` → `BACKED-verified` (with flake/n-rerun/`TEMPORALLY-UNVERIFIABLE` handling) · subagent-
  sidechain ingestion · adversarial fake-pass hardening.
  - **Shipped:** *jest/npm/go failure-summary literacy* — outcome-reading now recognizes the jest/vitest/npm
    summary (counts + an `N total` clause; duration on a separate `Time:` line) and go's package-result line
    (`ok|FAIL <pkg> <t>s`), alongside pytest and cargo. Same discipline as v1: read only off a framework-authored
    summary line, per-line, and accuse only on a non-zero exit — a bare `FAIL` word or an echoed log never accuses
    (anchor re-checked: 0 CONTRADICTED / 400 real sessions). Flip mutants for these runners are now generated and
    measured (previously excluded), so the catch-rate can regress-fail. Genuinely-unread runners (e.g. mocha) stay
    excluded rather than mislabeled.
- **Deferred (v2+):** the de-fanged one-shot "State of Agent Honesty" report (never a live curated leaderboard).

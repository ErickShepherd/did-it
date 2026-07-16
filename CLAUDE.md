# Claude Code guidance

Read this file before changing the repository.

## Current planning records

- [`docs/reviews/2026-07-16-independent-falsification-assessment.md`](docs/reviews/2026-07-16-independent-falsification-assessment.md)
  accepts the technical BLOCK while recording that the launcher substituted Fable 5 for the
  requested Opus 4.6. A later owner-instructed turn persisted the record using the reviewing
  session rather than a separate recorder. It recommends restoring local `main` for governance,
  not code-safety, subject to an explicit owner decision.
- [`docs/operations/l05-ledger-2026-07-16.md`](docs/operations/l05-ledger-2026-07-16.md) is the
  draft owner-scoped remediation charter for PIR-1/PIR-3/PIR-4 and ADJ-A/B/D/E/F. It is not
  executable until every pre-loop decision and gate is checked by an out-of-loop owner/calibrator.
- [`docs/reviews/2026-07-16-l05-charter-critique.md`](docs/reviews/2026-07-16-l05-charter-critique.md)
  is a same-session critique of charter v1 and the assessment (satisfies no gate). Charter v2
  incorporates its bounded test-authorization, ordering, containment, and record-accuracy findings;
  every owner decision and pre-loop gate remains unchecked.
- [`docs/reviews/2026-07-16-post-ralph-inspection.md`](docs/reviews/2026-07-16-post-ralph-inspection.md)
  is the current acceptance state. It records four open findings discovered after the L0 Ralph
  loop; treat the prior sign-off as invalidated until they are independently reviewed.
- [`docs/reviews/2026-07-16-independent-falsification.md`](docs/reviews/2026-07-16-independent-falsification.md)
  technically corroborates all four PIR findings (disposition BLOCK), with adjacent counterexamples
  ADJ-A/B/D/E/F. The launcher used Fable 5 rather than the requested Opus 4.6; the review response
  itself was read-only, then the same session persisted it on the owner's subsequent instruction.
  The model substitution and lack of a separate recorder leave the independent-review gate open.
- [`docs/operations/claude-review-post-ralph-2026-07-16.md`](docs/operations/claude-review-post-ralph-2026-07-16.md)
  is the review-only prompt for a fresh Claude Opus 4.6 process to falsify those findings.
- [`docs/reviews/2026-07-15-adversarial-review.md`](docs/reviews/2026-07-15-adversarial-review.md)
  contains eight reproduced correctness findings, REV-1 through REV-8.
- [`docs/design/model-agnostic-ingestion.md`](docs/design/model-agnostic-ingestion.md) defines the
  neutral Session IR and adapter trust boundary.
- [`docs/design/cross-runtime-installation-plan.md`](docs/design/cross-runtime-installation-plan.md)
  defines the installation architecture and milestones M0 through M6.
- [`docs/operations/ralph-cross-runtime.md`](docs/operations/ralph-cross-runtime.md) is the
  authoritative guide for converting that work into Ralph loops.

## Non-negotiable constraints

- Never falsely accuse. Changes to extraction, evidence binding, reconciliation, or adapter
  capability can affect the `CONTRADICTED` path and require the gates in the Ralph guide.
- Missing, malformed, redacted, truncated, ambiguous, or unsupported evidence fails closed.
- A loop may implement and test an adapter, but it may not set or approve
  `accusation_ready=True`, promote an integration to Tier A, approve a schema freeze, merge, push,
  or publish a release.
- Keep fixtures fabricated. Never commit private transcripts or private anchor data.
- Do not broaden transcript/runtime support before M0 is complete and independently reviewed.

## Standard local gates

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
.venv/bin/python -m eval.run --split test
```

For accusation-path changes, also run the private honest-session anchor when it is available, as
specified in the Ralph guide. Passing self-authored tests is not an independent review.

## Ralph loop mechanics

Loops here follow the installed `/ralph-loop` skill (checklist anchor); the Ralph guide above is
this repo's application of it, and the skill is the authority on loop mechanics. Pin models by full
ID (e.g. `claude-opus-4-6` when the owner requests Opus 4.6), never the moving `opus` alias. Start
a fresh non-interactive Claude process for each ledger item and keep the completion signal
mechanical and recomputed from disk. Every spawned process environment arms `CLAUDE_LOOP_GUARD=1`
plus the `guard-one-unit.py` cap variables (see the Ralph guide's invocation section); an `export`
inside the session never reaches the hooks.

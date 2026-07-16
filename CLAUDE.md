# Claude Code guidance

Read this file before changing the repository.

## Current planning records

- [`docs/reviews/2026-07-16-post-ralph-inspection.md`](docs/reviews/2026-07-16-post-ralph-inspection.md)
  is the current acceptance state. It records four open findings discovered after the L0 Ralph
  loop; treat the prior sign-off as invalidated until they are independently reviewed.
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

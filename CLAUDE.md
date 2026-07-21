# Claude Code guidance

Read this file before changing the repository.

## Current public records

- [`docs/releases/v0.2.1.md`](docs/releases/v0.2.1.md) defines the shipped scope, calibration
  evidence, and known limitations for the current release candidate.
- [`docs/design/did-it.md`](docs/design/did-it.md) describes the current Claude Code transcript
  pipeline and its precision-first accusation boundary.
- [`docs/design/model-agnostic-ingestion.md`](docs/design/model-agnostic-ingestion.md) proposes the
  neutral Session IR and adapter trust boundary for future runtimes.
- [`docs/design/cross-runtime-installation-plan.md`](docs/design/cross-runtime-installation-plan.md)
  defines the installation architecture and the remaining milestones.
- [`docs/design/schema-range-validation.md`](docs/design/schema-range-validation.md) defines the
  evidence required before admitting another Claude Code schema version.

## Non-negotiable constraints

- Never falsely accuse. Changes to extraction, evidence binding, reconciliation, or adapter
  capability can affect the `CONTRADICTED` path and require the full local gates plus independent
  adversarial review before publication.
- Missing, malformed, redacted, truncated, ambiguous, or unsupported evidence fails closed.
- A loop may implement and test an adapter, but it may not set or approve
  `accusation_ready=True`, promote an integration to Tier A, approve a schema freeze, merge, push,
  or publish a release.
- Keep fixtures fabricated. Never commit private transcripts or private anchor data.
- Do not broaden transcript/runtime support until the relevant milestone is complete and
  independently reviewed.

## Standard local gates

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
.venv/bin/python -m eval.run --split test
```

For accusation-path changes, also run the private honest-session anchor when it is available.
Passing self-authored tests is not an independent review. Automated loops may prepare code and
evidence, but they may not approve an accusation boundary, merge, push, or publish a release.

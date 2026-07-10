# did-it

Mechanically check whether an AI coding agent's natural-language claims — "I ran the tests and they
pass", "I created the file", "the suite is green" — match what its **Claude Code session actually did**,
as recorded in the transcript.

> **Status: scaffolding.** This repository is a project skeleton. The design is captured in
> [`docs/design/did-it.md`](docs/design/did-it.md); the modules under `src/did_it/` are stubs pending
> implementation. Nothing here is functional yet.

## What it does (planned v1)

Point `did-it` at a Claude Code transcript. For each procedural claim the agent made, it reports a
per-claim receipt:

- **BACKED** — the transcript shows the claim happening (e.g. a `pytest` result exited 0 at the time
  it was claimed).
- **UNSUPPORTED** — no supporting evidence found (the safe default; all ambiguity lands here).
- **CONTRADICTED** — the evidence contradicts the claim (e.g. "tests pass" but the last relevant test
  result was non-zero). The only accusation, held to a high bar.
- **NOT-CHECKABLE** — a semantic claim ("fixed the bug") the transcript can't adjudicate.
- **NOT-EVALUABLE** — the transcript can't be parsed, or the evidence lives somewhere this version
  doesn't read yet.

It exits non-zero only on `CONTRADICTED`, so it fits a CI step or a Claude Code Stop-hook.

## Scope (v1)

Deliberately narrow: Claude Code transcripts, one pinned schema, **procedural** claims (test runs,
commands, file operations), reconciled against the session's own tool-call evidence. Narrow-and-correct
over broad-and-flaky — a verifier that mis-verifies is worse than none.

## Prior art & credit

This addresses the same *claim-vs-evidence* problem named by **NabaOS** ("Tool Receipts, Not
Zero-Knowledge Proofs", arXiv:2603.10060) and by **METR**, whose evaluators reconcile agent claims
against reality by hand. `did-it`'s contribution is the specific, adopted, coding-specialized tool:
Claude Code transcripts reconciled against git-diff / exit-codes / test output.

## Development

```bash
pip install -e '.[dev]'
pytest
```

## License

MIT — see [`LICENSE`](LICENSE).

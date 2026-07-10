# fixtures/

Fabricated Claude Code transcript fixtures over **throwaway / public toy repos** — the published,
reproducible eval material (design doc D7/D8). These contain **no real session content**.

Rules (enforced by `scripts/leak_gate.py`):

- Every committed fixture must contain the marker string `FIXTURES_ONLY`.
- No private paths (`/home/`, `/Users/`), real repo names, or PII.

Real transcripts are **never** placed here — the private execution-labeled anchor lives under
`eval/anchor/` and is gitignored.

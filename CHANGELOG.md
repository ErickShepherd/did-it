# Changelog

All notable release changes are recorded here. The project follows semantic versioning while the
public API is pre-1.0.

## [0.2.1] - 2026-07-21

### Changed

- Migrated every JavaScript-based workflow dependency to a Node.js 24-native major.
- Expanded CI and release verification across every supported stable CPython minor from 3.10
  through 3.14.
- Pinned the successfully tested Ruff, pytest, build, Twine, and Hatchling versions used by CI
  and release builds so an unrelated tool release cannot change an unchanged candidate.
- Refreshed release metadata for the v0.2.1 maintenance release; runtime behavior and the
  Claude Code transcript scope are unchanged from v0.2.0.

## [0.2.0] - 2026-07-19

### Changed

- Hardened the sole `CONTRADICTED` path against scope, runner-family, compound-command, temporal,
  partial-quantity, and ambiguous-summary false accusations.
- Made `BACKED-transcript` command binding coherent across executable and path tokens, and added
  conservative abstention for unrecognized command names.
- Corroborated pass- and fail-oriented quantities and claim scope before issuing backed receipts.
- Extended validated Claude Code transcript admission through schema `2.1.207`.
- Added deterministic pytest-family, Cargo, Jest/npm, and Go runner literacy.
- Added held-out false-endorsement precision gates, fabricated adversarial fixtures, and hardened
  Ralph-loop containment evidence.
- Broadened the privacy leak gate: the no-argument run now scans the whole tracked tree for real
  home paths and concrete key shapes, not only `fixtures/`.

### Known limitations

- Claude Code schemas newer than `2.1.207` fail closed to `NOT-EVALUABLE` pending validation.
- Four documented permissive-direction receipt gaps can still produce false
  `BACKED-transcript` results; none can produce `CONTRADICTED`.
- Cross-runtime Session IR, canonical `did-it-json`, installers, and external recorders remain
  roadmap work; this release supports Claude Code transcripts only.

[0.2.0]: https://github.com/ErickShepherd/did-it/compare/v0.1.0...v0.2.0
[0.2.1]: https://github.com/ErickShepherd/did-it/compare/v0.2.0...v0.2.1

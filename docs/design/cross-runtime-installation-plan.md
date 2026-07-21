# Cross-runtime installation and distribution plan

**Status:** proposed implementation plan, 2026-07-15.
**Product term:** agent-runtime agnostic, not "installable into an LLM."
**Depends on:** [model-agnostic ingestion](model-agnostic-ingestion.md), the current
[release scope and limitations](../releases/v0.2.1.md), and independent validation before any
new runtime is allowed to issue accusations.
**Execution boundary:** this document is a staged design plan, not authorization to run an
autonomous implementation loop, merge, push, or publish.

## Outcome

A user should be able to install one local `did-it` tool, connect it to a supported coding-agent
runtime, and receive deterministic receipts without asking the model to report its own evidence.
The verifier should work regardless of the model provider or model ID.

The target experience is:

```console
$ uv tool install did-it
$ did-it init claude-code
$ did-it doctor
claude-code recorder: configured
canonical event stream: complete
backing verdicts: enabled
contradiction verdicts: enabled
```

Other intended entry points are:

```console
did-it init github-copilot
did-it init openai-agents --print-snippet
did-it init otel --print-profile
did-it check session.did-it.jsonl
did-it doctor --format json
did-it mcp                         # optional query surface; not the recorder
```

The exact command names are provisional. The trust boundaries and fail-closed behavior are not.

## Product boundary

`did-it` cannot be installed *into* a foundation model. It can be installed beside the runtime that
executes the model's tool calls and emits its visible response.

```text
agent runtime
  |-- lifecycle hooks / trace processor / SDK middleware
  v
did-it recorder adapter
  v
canonical did-it-json event stream
  v
shared deterministic verifier
  |-- text receipt
  |-- JSON receipt
  `-- optional MCP query interface
```

The recorder is the sensor. The verifier is the adjudicator. MCP, a skill, a prompt, or a model tool
is only a user interface: none is trusted to provide a complete account of what the agent did.

Consequences:

- a model instruction that says "call `did-it` before stopping" is convenience, not enforcement;
- an MCP server can expose verification tools but cannot certify that it observed calls made
  elsewhere in the host;
- rendered chat exports without typed, ordered tool events can support claim inventory, not
  transcript-time accusations;
- model metadata remains opaque provenance and never selects a verdict rule.

## Deliverables

### 1. One installable distribution

Keep one `did-it` Python distribution through the first two external integrations. Preserve the
stdlib-only verification hot path. Integrations needing vendor packages should be optional extras or
copyable snippets, not mandatory dependencies.

Proposed layout:

```text
src/did_it/
  ir.py
  adapters/
    base.py
    claude_code.py
    did_it_json.py
  recorders/
    openai_agents.py
    otel.py
  installers/
    base.py
    claude_code.py
    github_copilot.py
  schemas/
    did-it-session-v1.schema.json
  doctor.py
  mcp_server.py                  # optional, later phase
```

Do not split adapters into separate releases until dependency conflicts or release cadence make that
necessary. A single package keeps the early compatibility matrix and security-update path under one
version.

### 2. Canonical recorder format

Publish `did-it-json` v1 as JSONL with a checked JSON Schema and fabricated examples. It records
observations only: visible messages, calls, results, file changes, ordering, provenance, capability
declarations, and integrity facts. It never accepts source-provided verdicts or evidence tiers.

Provide a small streaming emitter API that validates IDs and events, represents truncation and
redaction explicitly, writes locally by default, and leaves a partial session explicitly incomplete
after a runtime crash. The schema and emitter are the public integration contract. Native log formats
remain adapter implementation details.

### 3. Recorder and adapter manifest

Every built-in integration declares a static, release-owned manifest:

```toml
id = "github-copilot"
integration_version = "0.1"
supported_source_versions = ["..."]
captures_visible_messages = true
captures_paired_tool_results = true
captures_shell_exit_codes = false
captures_verbatim_tool_output = true
captures_typed_file_changes = false
captures_branch_parentage = false
backing_ready = false
accusation_ready = false
```

Readiness fields ship with the package. A transcript, local configuration, or third-party emitter
cannot raise them. Per-session missing evidence can reduce capability but never increase it.

### 4. Safe integration installer

`did-it init <runtime>` should be an auditable configuration editor. It should:

1. locate the runtime and supported configuration files;
2. show the exact proposed change;
3. refuse unknown versions or ambiguous locations;
4. preserve unrelated settings and create a timestamped backup;
5. validate the resulting configuration;
6. support `--dry-run`, `--print-snippet`, and a narrowly scoped `uninstall`;
7. never download or execute runtime code during initialization.

Where programmatic editing is unsafe, `--print-snippet` is the supported path. Prefer runtime-owned
hook and trace APIs over scraping private databases or rendered terminal output.

### 5. Capability diagnostics

`did-it doctor` should report the detected runtime and source version, recorder status, last valid
canonical event, missing/redacted evidence, enabled verdict classes, support tier, and configuration
drift. Doctor results are diagnostics, not evidence, and cannot override a session's integrity state.

### 6. Optional MCP interface

After canonical ingestion is stable, a local MCP server may expose:

- `check_session(path)`;
- `list_claims(receipt)`;
- `explain_verdict(receipt, claim_id)`;
- `integration_status()`.

It should consume recorded sessions or receipts, bind file access to configured roots, and use the
same core API as the CLI. It must not let a model submit uncorroborated events and label them trusted.
MCP is a portable interface, not the evidence-capture mechanism.

## Support tiers

| Tier | Minimum source properties | Allowed output | Label |
|---|---|---|---|
| A — calibrated observer | Visible final text, ordered typed calls/results, integrity checks, source-specific mutation and honest-session calibration | All verdicts, including `CONTRADICTED` | Supported |
| B — structured but incomplete | Visible text and some paired events, with missing fields explicit | `BACKED` where sufficient plus abstentions; never `CONTRADICTED` | Experimental |
| C — rendered conversation | Visible prose without a trustworthy complete event stream | Claims and `NOT-EVALUABLE`/`NOT-CHECKABLE` only | Parse-only |
| D — self-reported | Model is asked to summarize or call a receipt tool after the fact | No evidence verdict | Unsupported |

A new model inside a calibrated runtime needs no new adapter unless it changes observable event
semantics. Promotion happens only in a reviewed release and may be revoked after source schema drift.

## Integration order

1. **Claude Code reference adapter.** Move the existing reader behind Session IR without changing
   receipts. It remains the parity oracle and first Tier A integration.
2. **Canonical `did-it-json`.** Release schema, parser, emitter, and conformance fixtures before
   another vendor adapter. Schema validity alone does not make input Tier A; the trusted recorder
   profile determines the verdict ceiling.
3. **GitHub Copilot.** Build from documented session/tool lifecycle hooks and begin at Tier B.
   Promote only if the supported host exposes visible final messages, result pairing, completion
   status, output completeness, file changes, and ordering.
4. **OpenAI Agents SDK.** Ship a local trace processor or middleware emitter, not hosted-UI scraping.
   Define a tool-result envelope for shell status, completeness, file operation kind, and visible
   response boundaries. Begin at Tier B.
5. **Version-pinned OpenTelemetry profile.** Define required spans, attributes, ordering, content
   policy, and unknown states. Reject generic GenAI telemetry that does not satisfy that profile.
6. **Later integrations.** Add native adapters only when stronger or easier than canonical emission.
   Rendered chat remains Tier C; web chats without host event APIs remain out of scope.

## Milestones and gates

### M0 — correctness prerequisites

- Resolve REV-1 through REV-8.
- Add false-endorsement precision to the evaluation headline.
- Keep tests, lint, leak gate, and held-out evaluation green.

**Exit gate:** no known P1 defect remains on the shared adjudication path.

### M1 — neutral core and Claude parity

- Implement immutable Session IR, adapter protocol, capability ceiling, and integrity diagnostics.
- Normalize Claude Code through the new adapter.
- Preserve the Python API and CLI defaults; namespace evidence references by source.

**Exit gate:** every existing fixture retains its receipt, temporal relationships, and exit code.

### M2 — canonical SDK and conformance kit

- Publish schema v1, parser, streaming emitter, fabricated examples, and a conformance command.
- Add explicit format selection and conservative detection.
- Test duplicates, orphans, truncation, redaction, unsupported versions, partial streams, resource
  limits, and unknown event kinds.

**Exit gate:** equivalent Claude/canonical sessions yield equivalent receipts; malformed and
ambiguous input fails closed.

### M3 — installation UX

- Implement installer dry-run, backups, targeted uninstall, and `doctor`.
- Add Claude Code initialization and manual configuration guidance.

**Exit gate:** install, reinstall, drift detection, and uninstall are idempotent in isolated fixture
homes on each supported platform; unrelated configuration is byte-for-byte preserved.

### M4 — first external recorder

- Implement GitHub Copilot recording as Tier B.
- Add source-native fixtures and a fabricated end-to-end recording.
- Measure coverage and false endorsement; mechanically disable accusations.

**Exit gate:** the recorder survives native schema/error mutants and `doctor` explains every
capability gap. Tier A promotion remains a separate release gate.

### M5 — SDK and telemetry integrations

- Add the OpenAI Agents recorder profile and example.
- Add the pinned OpenTelemetry profile after the canonical envelope stabilizes.
- Publish compatibility by did-it, integration, and admitted source versions.

**Exit gate:** each integration passes common conformance plus its source-native corpus, and detects
unsupported content/redaction settings before adjudication.

### M6 — optional MCP and ecosystem boundary

- Add the read-oriented MCP interface.
- Document how skills/plugins invoke it without entering the evidence trust chain.
- Define a third-party adapter checklist; do not load arbitrary parser plugins by default.

**Exit gate:** MCP and CLI return the same receipt, and MCP cannot raise the capability ceiling.

## Testing and release policy

Every integration release includes schema/adapter tests, cross-format equivalence, native malformed
and version-drift cases, native-format accusation mutants, a fabricated end-to-end recording where
practical, isolated installer tests, privacy/leak scanning, and a compatibility-table update.

Tier A promotion requires a reviewed calibration record, zero false accusations on the admission
corpus, measured false-endorsement precision, and confirmation that the supported source versions
expose complete visible responses and tool results.

## Security and privacy constraints

- Treat transcripts, tool arguments, outputs, and paths as sensitive local data.
- Keep recording and verification local by default; network export is opt-in.
- Enforce byte, nesting, event-count, and string-size limits before full expansion.
- Never execute transcript content during ingestion; existing opt-in `--verify` restrictions remain.
- Restrict configuration writes to known files and preserve permissions.
- Represent redaction/truncation as integrity state instead of inferring content.
- Keep fixtures fabricated and run the leak gate over every new corpus.

## Documentation and release artifacts

Before announcing cross-runtime support, publish runtime-organized installation docs, the canonical
schema/emitter guide, a compatibility and verdict-ceiling table, the MCP/self-report threat boundary,
recorder privacy/uninstall instructions, and a Claude Code compatibility note.

Change the project description from "Claude Code session" to "supported coding-agent session" only
after an external runtime passes M4. Until then, this broader architecture remains planned.

## Decisions intentionally deferred

- Whether external adapters eventually become separate distributions.
- Whether receipts need signatures or content-addressed session bundles.
- Whether a process boundary can make untrusted third-party adapters safe.
- Which external runtime, if any, can meet the Tier A observer bar.
- Whether the MCP server belongs in the base install or an optional extra.

These do not block the neutral IR, canonical format, installer framework, or first Tier B recorder.

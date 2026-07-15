# Model- and runtime-agnostic ingestion — feasibility and design

**Status:** proposed investigation record, 2026-07-15.
**Decision:** feasible, but only through a versioned neutral event model plus source adapters.
**Prerequisite:** close the P1 findings in
[`../reviews/2026-07-15-adversarial-review.md`](../reviews/2026-07-15-adversarial-review.md)
before enabling accusations for any new source.

## Executive answer

`did-it` is already largely **model-agnostic** when a model runs inside Claude Code: extraction
reads visible assistant prose, reconciliation reads tool activity, and no rule depends on a model
identifier. The hard-coded boundary is the **agent runtime and transcript format**, not the model.

Making the product work across coding agents is possible. The safe design is:

```text
source transcript/trace
        |
        v
strict versioned adapter  -- missing/ambiguous facts --> NOT-EVALUABLE
        |
        v
did-it Session IR (ordered visible messages + typed tool/change events + integrity flags)
        |
        +--> deterministic claim extraction
        +--> shared evidence index
                         |
                         v
                    reconciliation
```

The first new input should be a documented canonical `did-it-json` format that any runtime can
emit. Native vendor adapters should come later. This provides immediate model/runtime independence
without making the core guess every vendor's evolving private log shape.

## Terms: three different kinds of independence

| Axis | Current state | What is required |
|---|---|---|
| Model provider/model ID | Mostly independent already | Treat model metadata as opaque provenance; no model-specific claim rules |
| Agent runtime | Claude Code only | Normalize visible turns, tool calls/results, file changes, delegation, and ordering |
| Serialized format/version | Claude Code `2.1.156–2.1.207` only | One strict adapter and version policy per source, plus a canonical format |

Calling the work merely "model-agnostic" can hide the actual engineering risk. A GPT, Claude,
Gemini, local, or open-weight model can all produce the same event stream. Conversely, two agents
using the same model can expose incompatible evidence and require different adapters.

## Current coupling map

| Component | Model-specific? | Runtime/format-specific? | Refactor |
|---|---|---|---|
| `transcript.py` | No | Yes: Claude record types, content blocks, version range, sidechains | Move to `adapters/claude_code.py`; emit Session IR |
| `extraction.py` | No | Lightly: expects `Session.records` and Claude content blocks | Consume `visible_assistant_text()` from IR |
| `evidence.build_index()` | No | Yes: `Bash`, `Edit`, `Write`, `NotebookEdit`, Claude pairing | Consume typed IR tool/change events |
| runner/output literacy | No | No, once command/output are normalized | Keep shared, with scope fixes from the review |
| `reconcile.py` | No | Assumes information lost by the Claude-shaped index | Bind claims to typed IR evidence |
| `verify.py` | No | No, once it receives a validated command and repo | Keep shared |
| report/verdicts | No | No | Keep shared; namespace evidence references by source |

The refactor is therefore bounded: parsing and evidence normalization move behind adapters; claim
and outcome logic remain shared.

## Minimum Session IR

The IR must preserve facts, not vendor vocabulary. A representative Python shape is:

```python
@dataclass(frozen=True)
class SessionIR:
    source: str                 # "claude-code", "did-it-json", "openai-agents", ...
    source_version: str
    events: tuple[Event, ...]   # stable total order
    capabilities: Capabilities
    integrity: Integrity
    model_provenance: tuple[str, ...] = ()  # opaque; never used to choose a verdict

@dataclass(frozen=True)
class VisibleMessage:
    seq: int
    role: Literal["user", "assistant"]
    text: str
    ref: str
    branch: str | None

@dataclass(frozen=True)
class ToolCall:
    seq: int
    call_id: str
    kind: Literal["shell", "file_create", "file_edit", "notebook_edit", "subagent", "other"]
    name: str
    arguments: Mapping[str, object]
    ref: str

@dataclass(frozen=True)
class ToolResult:
    seq: int
    call_id: str
    status: Literal["ok", "error", "interrupted", "unknown"]
    exit_code: int | None
    output: str | None
    output_complete: bool
    ref: str
```

File operations need exact normalized paths and explicit operation kinds. Shell events need the
verbatim command, completion status, exit code when known, output, and an output-truncation flag.
Delegated events need a branch/parent relationship rather than one session-wide boolean.

### Mandatory integrity rules

An adapter must fail closed when any consumed fact is malformed or ambiguous:

- sequence numbers are unique and define a stable total order;
- visible assistant text is distinguishable from reasoning, hidden prompts, quoted logs, and tool
  output;
- every consumed result pairs with exactly one call ID;
- source/schema version is present and admitted by that adapter's validated range;
- truncation/redaction is explicit; absent output is not an empty successful output;
- file paths are source-faithful and normalized without discarding directories;
- sidechains/handoffs retain parentage, or the affected claims become `NOT-EVALUABLE`;
- duplicate IDs, orphan results, unknown success states, and mixed unsupported versions never
  receive inferred defaults.

The IR should be immutable after parsing. Evidence references should be namespaced, for example
`openai-agents:span_123`, so receipts remain meaningful across formats.

## Adapter contract

```python
class TranscriptAdapter(Protocol):
    name: str

    def sniff(self, path: Path) -> Detection: ...
    def parse(self, path: Path) -> SessionIR: ...
```

`Detection` must distinguish `MATCH`, `NO_MATCH`, and `AMBIGUOUS`. The CLI should support an
explicit `--format`; auto-detection may be convenient, but zero or multiple matches must return a
session-level `NOT-EVALUABLE`, never pick the first parser.

Each adapter declares capabilities separately from integrity:

```python
@dataclass(frozen=True)
class Capabilities:
    visible_messages: bool
    paired_tool_results: bool
    shell_exit_codes: bool
    verbatim_tool_output: bool
    typed_file_changes: bool
    branch_parentage: bool
    backing_ready: bool
    accusation_ready: bool
```

`accusation_ready` is a release gate, not a transcript-provided flag. New adapters default to
`False`; the reconciler cannot emit `CONTRADICTED` until the adapter passes source-specific
calibration. Missing per-session evidence still abstains even for a calibrated adapter.

## Representative source feasibility

### Claude Code: reference adapter

The existing parser becomes the reference adapter. Its first migration must be behavior-preserving:
every committed fixture produces the same claims, verdicts, notes, and temporal relationships before
and after normalization (evidence reference prefixes may differ). This is the oracle for the IR.

### Canonical `did-it-json`: recommended first new format

Publish a small JSONL schema that directly represents the IR, with its own semantic version. Any
agent, SDK, hook, or test harness can emit it without waiting for a built-in adapter. This is the
shortest path to true model/runtime independence and gives adapter authors a conformance target.

The canonical format should not contain verdicts or preclassified outcomes. It records observations;
`did-it` computes evidence tiers and verdicts so an input cannot forge trust.

### OpenAI Agents SDK traces: feasible with an exporter profile

The current Agents SDK traces generations, function calls, handoffs, guardrails, and custom events.
Spans carry trace/parent IDs and start/end timestamps. `FunctionSpanData` exports a function name,
input, and output, and custom trace processors can receive completed spans and export them locally.
Those are strong adapter primitives.

Two constraints prevent treating an arbitrary trace as accusation-ready:

1. generation and function inputs/outputs are sensitive-data fields and may be disabled; a
   content-redacted trace cannot establish visible claims or verbatim failure evidence;
2. a generic function output does not necessarily expose shell exit code, output completeness, file
   operation, or user-visible final-message boundaries. The coding-agent instrumentation must emit
   those facts through a documented tool schema or custom events.

Recommendation: provide a small trace processor that writes canonical `did-it-json` at runtime.
Do not scrape the hosted trace UI or assume all function tools are shell commands.

### OpenTelemetry GenAI spans: useful interchange, not sufficient by itself

Current GenAI semantic conventions define agent invocation and tool execution concepts, including
tool-call IDs, arguments, and results. That makes OpenTelemetry a promising transport/profile for
the IR. However, the GenAI conventions are still marked as development in relevant areas, message
and tool content is commonly opt-in because it is sensitive, and generic tool results do not imply
shell exit semantics.

Recommendation: define a version-pinned `did-it` OpenTelemetry profile rather than accepting any
GenAI trace. The profile must require the same integrity facts as canonical `did-it-json`; otherwise
the adapter remains parse-only or abstention-only.

### Aider: model-flexible, but its documented chat log is insufficient for accusations

Aider itself can use many model providers. It documents Markdown chat history, an optional LLM
history log, `/run`, `/test`, file editing, and Git integration. The public history format is useful
for visible prose, but it is not documented as a stable typed event stream that always pairs commands,
exit codes, outputs, file operations, and message timing.

Recommendation: ingest Aider only through an instrumented exporter to canonical `did-it-json`, or
ship an experimental adapter that cannot emit `CONTRADICTED`. Parsing `.aider.chat.history.md` alone
would recreate the log-grep ambiguity this project was designed to avoid.

### Other runtimes

A runtime is supportable if it can provide the minimum IR facts. If it exports only a rendered
chat, screenshots, final prose, or repository diffs without utterance-time tool ordering, it can
support claim inventory only. `BACKED-verified` additionally requires a trusted integration to
supply the claim's validated command; such a source cannot safely support transcript-time accusations.

## Migration plan

### Phase 0 — repair shared correctness

Close REV-1 through REV-8 and extend the evaluation with false-endorsement precision. Generalizing
before that point would multiply known false-verdict behavior across adapters.

### Phase 1 — introduce IR behind the existing API

1. Add `ir.py` with immutable events, capabilities, integrity diagnostics, and limits.
2. Move Claude parsing to `adapters/claude_code.py`.
3. Make `extraction` consume visible messages and `evidence` consume typed events.
4. Preserve `did_it.check(path)` and CLI behavior; default format remains Claude Code.
5. Require exact receipt parity across every existing fixture.

### Phase 2 — canonical interchange

1. Specify `did-it-json` v1 and publish fabricated examples.
2. Add `--format did-it-json`; optionally add conservative detection.
3. Provide a tiny emitter library/helper, not a second adjudication implementation.
4. Generate the same synthetic session into Claude and canonical forms and require cross-format
   receipt equivalence.

### Phase 3 — one instrumented external runtime

Use an SDK/runtime with structured lifecycle hooks, initially as experimental and
`accusation_ready=False`. OpenAI Agents SDK plus a local custom trace processor is a plausible first
candidate because the required span/export seams are documented. Promote only after the validation
bar below passes.

### Phase 4 — optional telemetry and native adapters

Add a version-pinned OpenTelemetry profile and native adapters only where they improve adoption.
Avoid third-party parser plugins until the adapter trust boundary and resource limits are stable;
an unsafe parser can undermine the whole process before fail-closed reconciliation runs.

## Validation bar for every adapter

An adapter is not accusation-ready merely because it parses fixtures.

1. **Conformance:** malformed records, duplicate IDs, orphan results, redaction, truncation,
   unsupported versions, mixed branches, and oversized inputs all fail closed.
2. **Cross-format equivalence:** semantically identical fabricated sessions yield identical claims
   and verdicts after normalization.
3. **Native-shape corpus:** source-native fabricated fixtures exercise every consumed event shape and
   unknown-event behavior.
4. **Honest-session anchor:** run end to end on a meaningful source-native honest-session sample;
   any `CONTRADICTED` is adjudicated before promotion. A code-changing adapter migration requires a
   fresh anchor, analogous to the existing schema-range policy.
5. **Accusation mutants:** fake-pass mutations must be expressed in the native source format, not
   injected after normalization.
6. **BACKED precision:** measure false endorsement as well as coverage.
7. **Resource limits/privacy:** adapters enforce byte/depth/count limits before whole-input expansion,
   and fixtures/leak gates remain fabricated-only.

## Decision matrix

| Option | Independence gained | Safety | Recommendation |
|---|---|---|---|
| Keep Claude parser only; ignore model ID | Model-agnostic within Claude Code | Current | Already true, but narrow |
| Add regex parsers for rendered chat logs | Superficial runtime coverage | Poor | Reject |
| Add native adapters directly to current `Session.records` | Some runtime coverage | Fragile Claude-shaped abstraction leaks | Reject |
| Introduce Session IR, then native adapters | Model and runtime independence | Strong if adapters are calibrated | Accept |
| Publish canonical `did-it-json` first | Immediate integration path for any runtime | Strongest and smallest first step | **Recommended** |
| Treat arbitrary OpenTelemetry GenAI spans as complete evidence | Broad transport compatibility | Content and shell semantics may be absent | Reject; require a profile |

## Sources checked

External interfaces are time-sensitive; these were checked on 2026-07-15:

- [OpenAI Agents SDK tracing](https://openai.github.io/openai-agents-python/tracing/): traced
  generations/tool calls/handoffs, sensitive-content behavior, and custom processors.
- [OpenAI Agents SDK tracing reference](https://openai.github.io/openai-agents-python/ref/tracing/):
  `FunctionSpanData` input/output and span processor interfaces.
- [OpenTelemetry GenAI attributes](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/):
  tool-call ID, arguments/results, operation names, and development-status conventions.
- [Aider configuration](https://aider.chat/docs/config/aider_conf.html): chat input/history and LLM
  history files.
- [Aider commands](https://aider.chat/docs/usage/commands.html) and
  [lint/test behavior](https://aider.chat/docs/usage/lint-test.html): `/run`, `/test`, and chat-history
  behavior.

These sources establish feasibility, not compatibility. Each future adapter still needs native
fixtures and calibration against the exact version it supports.

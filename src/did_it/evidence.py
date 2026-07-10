"""Evidence binding — locate the tool_use/tool_result events that ground (or contradict) a claim.

Design: docs/design/did-it.md — "Approach" step 2. Reuses the evidence-tier idea from the conformance
spine (an internal conformance checker): tiers are computed, never author-written,
so they can't be forged. Evidence is indexed to utterance-time: a grounding run must fall at/before
the claim AND after the last relevant edit (a post-run edit invalidates a prior outcome).

The index is built once per session:
  * Run    — a completed Bash tool_use/tool_result pair, with the parsed exit code.
             Failure encoding (measured on real transcripts): tool_result.is_error=true and
             content prefixed "Exit code N". is_error without a parsable code (interruption,
             permission denial) yields exit_code=None — not green, and never a contradiction
             witness (D4: accusations need a verbatim exit-code span).
  * Change — an Edit/Write tool_use (the temporal-guard events).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Commands whose green/red outcome adjudicates a test-pass claim. Published on purpose.
TEST_RUNNERS = re.compile(
    r"\b(?:pytest|py\.test|python3?\s+-m\s+(?:pytest|unittest)|unittest|"
    r"(?:npm|yarn|pnpm|bun)\s+(?:run\s+)?test|cargo\s+test|go\s+test|make\s+(?:test|check)|"
    r"tox|nox|ctest|rspec|jest|vitest|mvn\s+test|gradle(?:w)?\s+test)\b"
)

EXIT_CODE_SPAN = re.compile(r"^Exit code (\d+)", re.M)


@dataclass
class Run:
    """A completed Bash command with its observed outcome."""

    index: int                     # record index of the tool_result (evidence exists HERE)
    command: str
    exit_code: int | None          # 0 green; >0 red; None = errored without a parsable code
    output: str                    # result content (the verbatim-span source)
    ref: str                       # tool_use id
    is_test_run: bool

    @property
    def contradiction_span(self) -> str | None:
        """The verbatim 'Exit code N' line D4 requires, if this run can support an accusation."""
        m = EXIT_CODE_SPAN.search(self.output)
        return m.group(0) if m and self.exit_code else None


@dataclass
class Change:
    """An Edit/Write tool_use — the events the temporal guard is measured against."""

    index: int
    path: str
    tool: str
    ref: str


@dataclass
class Evidence:
    """A tool_use/tool_result pair bound to a claim."""

    tool: str                      # e.g. "Bash"
    ref: str                       # tool_use id
    exit_code: int | None = None
    at_index: int | None = None
    tier: str = "unproven"         # witness (exit-code-grounded) / unproven
    span: str | None = None        # verbatim contradicting span, when contradicting


@dataclass
class Index:
    """All evidence events of a session, in record order."""

    runs: list[Run]
    changes: list[Change]

    def runs_before(self, idx: int, *, test_only: bool = False) -> list[Run]:
        return [r for r in self.runs if r.index < idx and (r.is_test_run or not test_only)]

    def changes_between(self, lo: int, hi: int) -> list[Change]:
        return [c for c in self.changes if lo < c.index < hi]


def _result_text(block_content) -> str:  # noqa: ANN001  (str | list per schema)
    if isinstance(block_content, str):
        return block_content
    if isinstance(block_content, list):
        return "\n".join(
            b.get("text", "") for b in block_content if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def build_index(session) -> Index:  # noqa: ANN001
    """Pair every tool_use with its tool_result and classify the outcome."""
    pending: dict[str, tuple[int, str, dict]] = {}  # id -> (use index, tool name, input)
    runs: list[Run] = []
    changes: list[Change] = []
    for idx in range(len(session.records)):
        for block in session.content_blocks(idx):
            btype = block.get("type")
            if btype == "tool_use" and isinstance(block.get("id"), str):
                pending[block["id"]] = (idx, block.get("name") or "", block.get("input") or {})
            elif btype == "tool_result":
                use = pending.pop(block.get("tool_use_id"), None)
                if use is None:
                    continue
                _, name, tool_input = use
                output = _result_text(block.get("content"))
                if name == "Bash":
                    command = str(tool_input.get("command") or "")
                    if block.get("is_error"):
                        m = EXIT_CODE_SPAN.search(output)
                        exit_code = int(m.group(1)) if m else None
                    else:
                        exit_code = 0
                    runs.append(
                        Run(
                            index=idx,
                            command=command,
                            exit_code=exit_code,
                            output=output,
                            ref=block["tool_use_id"],
                            is_test_run=bool(TEST_RUNNERS.search(command)),
                        )
                    )
                elif name in ("Edit", "Write", "NotebookEdit") and not block.get("is_error"):
                    changes.append(
                        Change(
                            index=idx,
                            path=str(tool_input.get("file_path") or ""),
                            tool=name,
                            ref=block["tool_use_id"],
                        )
                    )
    return Index(runs=runs, changes=changes)


def last_relevant_edit_index(index: Index, run: Run, claim_index: int) -> int | None:
    """Index of the latest Change between a run and the claim, if any.

    v1 conservative default (design "Open questions"): ANY post-run Edit/Write invalidates a
    prior outcome — we do not attempt dependency analysis between edited files and the command.
    """
    between = index.changes_between(run.index, claim_index)
    return between[-1].index if between else None


def find_evidence(index: Index, claim) -> Evidence | None:  # noqa: ANN001
    """The Evidence grounding/contradicting a test-outcome claim at utterance-time, or None.

    Uses the LAST test run before the claim; a Change after that run voids it (returns None:
    the claim is then unsupported, never contradicted).
    """
    test_runs = index.runs_before(claim.utterance_index, test_only=True)
    if not test_runs:
        return None
    run = test_runs[-1]
    if last_relevant_edit_index(index, run, claim.utterance_index) is not None:
        return None  # temporal guard: outcome may have changed since the run
    return Evidence(
        tool="Bash",
        ref=run.ref,
        exit_code=run.exit_code,
        at_index=run.index,
        tier="witness",
        span=run.contradiction_span,
    )

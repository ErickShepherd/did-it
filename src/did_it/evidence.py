"""Evidence binding — locate the tool_use/tool_result events that ground (or contradict) a claim.

Design: docs/design/did-it.md — "Approach" step 2. Reuses the evidence-tier idea from a sibling
conformance-checking project: tiers are computed, never author-written, so they can't be forged.
Evidence is indexed to utterance-time: a grounding run must fall at/before the claim AND after
the last relevant edit (a post-run edit invalidates a prior outcome).

The index is built once per session:
  * Run    — a completed Bash tool_use/tool_result pair, with the parsed exit code.
             Failure encoding (measured on real transcripts): tool_result.is_error=true and
             content prefixed "Exit code N". is_error without a parsable code (interruption,
             permission denial) yields exit_code=None — not green, and never a contradiction
             witness (D4: accusations need a verbatim exit-code span).
  * Change — an Edit/Write tool_use (the temporal-guard events).
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass

#: Commands whose green/red outcome adjudicates a test-pass claim. Published on purpose.
#: Anchored to a COMMAND POSITION (line start, or after && || ; | $( or an env-var prefix):
#: `pip install pytest`, `grep pytest`, and heredoc bodies mentioning a runner are not runs.
_RUNNER = (
    r"(?:\S*/)?(?:pytest|py\.test|python3?\s+-m\s+(?:pytest|unittest)|"
    r"(?:npm|yarn|pnpm|bun)\s+(?:run\s+)?test\b|cargo\s+test|go\s+test|make\s+(?:test|check)|"
    r"tox|nox|ctest|rspec|jest|vitest|mvn\s+test|gradlew?\s+test|"
    r"uv\s+run\s+pytest)"
)
TEST_RUNNERS = re.compile(
    rf"(?:^|[;|]|&&|\|\||\$\(|`)\s*(?:[A-Z_][A-Z0-9_]*=\S+\s+)*{_RUNNER}\b",
    re.M,
)

EXIT_CODE_SPAN = re.compile(r"^Exit code (\d+)", re.M)

#: Quoted strings are stripped before runner-matching: a command that merely MENTIONS a runner
#: (`echo "pytest passed"`) is not a test run. Heredoc bodies likewise (notes that quote a
#: runner invocation were the top phantom-run source in the real anchor).
QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
#: Heredoc delimiter length gate. `(\w+)` (unbounded) backtracks quadratically on a SINGLE `<<`
#: followed by a long unbroken word with no terminator (3.6s at 40KB → hours at 1MB); the
#: opener-COUNT cap below does not catch a one-opener payload. Real delimiters
#: are short identifiers (EOF, PYEOF, …), so `{1,64}` bounds the backreference and the backtrack.
_HEREDOC_DELIM_CAP = 64
HEREDOC = re.compile(rf"<<-?\s*(['\"]?)(\w{{1,{_HEREDOC_DELIM_CAP}}})\1.*?^\2$", re.S | re.M)


#: HEREDOC's lazy body scan is quadratic on unterminated `<<X` floods (15.5s at 160KB) — each
#: opener scans to end-of-string. Capping
#: the OPENER COUNT bounds the total work to ~cap×len (a plain long command with few `<<`
#: strips linearly). An opener-flooded command is treated as NOT a test command, so it is
#: never a witness for OR against any claim. Caveat: this
#: drop also removes a would-be GREEN witness from the conflicting-green guard, so on a
#: crafted >64-opener green run the guard cannot suppress a later accusation — accepted
#: as implausible input; do not widen the cap or the guards assuming the drop is free.
_HEREDOC_OPENER_CAP = 64

#: TEST_RUNNERS (and the tool-position matcher) anchor at every chain operator and line
#: start, greedily scanning from each — an `&&`/newline flood is quadratic (26s at 160KB).
#: Real compound commands carry a handful of separators; a flooded
#: command is not evaluable as a witness (same abstain rationale as the heredoc cap).
_CHAIN_SEP_CAP = 64

#: Runner invocations that don't EXECUTE tests: their exit 0 carries no outcome evidence
#: (`pytest --version` exit-0 endorsed "All 500 tests pass").
_NON_EXECUTING = re.compile(
    r"\s--?(?:version|help|h\b|collect-only|co\b|fixtures|markers|setup-only|setup-plan|list)\b"
)


def _scan_bounded(command: str) -> bool:
    """A command whose scan cost is bounded; anything else is never a witness (abstain).

    The count must cover EVERY anchor the runner/tool matchers key on — `$(` and backtick
    floods hung identically until this cap covered them.
    """
    if command.count("<<") > _HEREDOC_OPENER_CAP:
        return False
    seps = (command.count("&&") + command.count("|") + command.count(";")
            + command.count("\n") + command.count("$(") + command.count("`"))
    return seps <= _CHAIN_SEP_CAP


def _stripped(command: str) -> str:
    return QUOTED.sub(" ", HEREDOC.sub(" ", command))


#: Bash sub-command separators, including newline and bare `&` (bash treats a newline like
#: `;`, and `&` backgrounds the preceding command). Omitting them lumped a multi-line or
#: backgrounded `--version` clause in with a real runner's clause and dropped its green run
#: (false CONTRADICTED). `&&` precedes `&` in the alternation so a chain operator is never
#: split into two. Splitting first means the per-clause runner scan never sees these anchors,
#: so the `_scan_bounded` linearity cap (which bounds `\n`) is preserved, not weakened. Shared
#: by `is_test_command` and `_runner_clause` so the two can't drift to different separator sets.
_CLAUSE_SEP = re.compile(r"&&|\|\||;|\||\n|&")


def _runner_clauses(command: str) -> list[str]:
    """Sub-commands that invoke a runner in EXECUTING form, in order.

    A clause qualifies iff it invokes a runner at a command position and is not a
    non-executing form (`--version`, `--collect-only`, …); `_NON_EXECUTING` is checked PER
    CLAUSE, not over the whole command, so an unrelated `--version` on a different
    sub-command never drops a real test run. Callers strip quoted/heredoc text first when
    mentions inside it must not count. Shared by `is_test_command`, `_runner_clause`, and
    `runner_family` so the three can't drift to different notions of "executed runner".
    """
    return [
        clause
        for clause in _CLAUSE_SEP.split(command)
        if TEST_RUNNERS.search(clause) and not _NON_EXECUTING.search(clause)
    ]


def is_test_command(command: str) -> bool:
    """True if the Bash command actually EXECUTES a test runner (not merely mentions one)."""
    if not _scan_bounded(command):
        return False
    return bool(_runner_clauses(_stripped(command)))

#: Test-framework outcome markers, deliberately narrow (anchor calibration: compound
#: Bash commands make the command exit code an unreliable witness for the TEST outcome — three
#: real sessions produced false CONTRADICTED from green-pytest-then-failing-tail / SIGPIPE /
#: ruff's "Found 1 error (1 fixed)" sitting next to a green pytest summary). Counts are only
#: read off the framework's own SUMMARY LINE (pytest's "... in N.NNs" line, cargo's
#: "test result:"), never from arbitrary output — an AssertionError traceback or another
#: tool's error count may belong to a neighbouring sub-command.
#: A summary line carries a count clause AND a duration clause (pytest), or the cargo
#: marker. Matched PER LINE with independent linear searches — the previous single
#: `^.*(...).*$` pattern backtracked quadratically on near-match floods (10s at 144KB,
#: extrapolating to hours on a multi-MB untrusted tool_result).
_SUMMARY_COUNTS = re.compile(r"\b\d[\d,]*\s+(?:passed|failed|errors?|skipped)\b")
_SUMMARY_TIME = re.compile(r"\bin\s+[\d.]+s\b")
_SUMMARY_CARGO = re.compile(r"\btest result: (?:ok|FAILED)\b")
#: jest/npm literacy (v1.1): the jest summary carries the counts and an "N total" clause,
#: but the duration is on a SEPARATE `Time:` line, so pytest's `in N.NNs` gate never
#: matched it. (vitest's native `Tests 12 passed (12)` has no `N total` and stays unread →
#: UNSUPPORTED, the safe direction — not claimed as covered.)
#: "N total" is the framework-authored anchor that distinguishes the summary
#: line from an incidental "1 failed" in prose. The trailing `(?!\s+\w)` keeps it to jest's
#: end-of-clause `N total` and off prose like "100 total records" (shrinks the incidental
#: accusation surface). Still per-line, still exit-gated for accusal.
_SUMMARY_TOTAL = re.compile(r"\b\d[\d,]*\s+total\b(?!\s+\w)")
#: go literacy (v1.1): go prints no counts — its summary is a package-result line
#: `ok|FAIL <pkg> <t>s` (tab-separated), analogous to cargo's marker. The <pkg>+<duration>
#: shape is what keeps a bare `FAIL` word (echoed logs, `--- FAIL:` per-test lines) from
#: reading as a summary. `(cached)` results carry no duration and are covered by exit-0 alone.
_SUMMARY_GO = re.compile(r"^(?:ok|FAIL)\s+\S+\s+[\d.]+s\b")
_FAILED_COUNT = re.compile(
    r"\b[1-9]\d*\s+(?:failed|errors?)\b|\btest result: FAILED\b|^FAIL\s+\S+\s+[\d.]+s\b", re.I
)
_PASSED_COUNT = re.compile(r"\b\d[\d,]*\s+passed\b|\btest result: ok\b|^ok\s+\S+\s+[\d.]+s\b")
#: pytest short-summary per-test lines are framework-authored and unambiguous on their own.
FAILED_LINE = re.compile(r"^(?:FAILED|ERROR)\s+\S+::", re.M)


def _is_summary_line(line: str) -> bool:
    # No length cap and no output truncation: every component search is linear, and any
    # bound that can drop a genuine green summary re-opens the false accusation
    # (a 256KB tail cap does exactly that).
    return bool(
        (_SUMMARY_COUNTS.search(line) and (_SUMMARY_TIME.search(line) or _SUMMARY_TOTAL.search(line)))
        or _SUMMARY_CARGO.search(line)
        or _SUMMARY_GO.search(line)
    )


@dataclass
class Run:
    """A completed Bash command with its observed outcome."""

    index: int                     # record index of the tool_result (evidence exists HERE)
    command: str
    exit_code: int | None          # 0 green; >0 red; None = errored without a parsable code
    output: str                    # result content (the verbatim-span source)
    ref: str                       # tool_use id
    is_test_run: bool

    @functools.cached_property
    def _summary_lines(self) -> list[str]:
        # Cached per instance (the dataclass is unfrozen, so cached_property may write to
        # __dict__): classify_outcome reads this several times (framework_failed/green/
        # contradiction_span each re-scan), and the scan is splitlines + per-line regex over
        # uncapped tool output. A Run's `output` never mutates after construction, so the cache
        # can't go stale.
        return [line for line in self.output.splitlines() if _is_summary_line(line)]

    @staticmethod
    def _summaries_conflict(lines: list[str]) -> bool:
        """A genuinely-green summary line AND a SEPARATE failure-summary line coexist.

        The two framework summaries disagree, so neither can be trusted as THE outcome of
        this run — the canonical case is an echoed/cat'd stale CI log's `N failed … in Ns`
        summary sitting beside a real green summary. Abstain: never accuse, never assert
        backed (the false-CONTRADICTED path this guards). A single mixed line
        (`5 failed, 3 passed in 12.01s`) is a genuine partial failure, not a conflict: it
        carries no green-*only* summary line, so it still reads as framework_failed."""
        green = any(_PASSED_COUNT.search(ln) and not _FAILED_COUNT.search(ln) for ln in lines)
        failed = any(_FAILED_COUNT.search(ln) for ln in lines)
        return green and failed

    @property
    def framework_failed(self) -> bool:
        """The test framework's own summary reported failures/errors.

        Per-test FAILED/ERROR lines count only when the output carries NO summary line at
        all (a truncated run). Next to a genuine summary they may be echoed content — a
        cat'd CI log's stale FAILED line beside a green summary produced a false
        accusation. Conflicting summaries (a green summary line AND a
        separate failure-summary line) are ambiguous, never a failure marker."""
        lines = self._summary_lines
        if lines:
            if self._summaries_conflict(lines):
                return False
            return any(_FAILED_COUNT.search(line) for line in lines)
        return bool(FAILED_LINE.search(self.output))

    @property
    def framework_green(self) -> bool:
        """The test framework's own summary reported passes and no failures."""
        lines = self._summary_lines
        if self._summaries_conflict(lines):
            return False  # conflicting summaries → ambiguous, not backed
        return any(_PASSED_COUNT.search(line) for line in lines) and not self.framework_failed

    @property
    def contradiction_span(self) -> str | None:
        """The verbatim span D4 requires: a non-zero exit AND the framework's own failure
        marker (a red compound command with green tests is never an accusation witness)."""
        if not self.exit_code or not self.framework_failed:
            return None
        exit_m = EXIT_CODE_SPAN.search(self.output)
        fail_span = next(
            (
                m.group(0).strip()
                for line in self._summary_lines
                for m in [_FAILED_COUNT.search(line)]
                if m
            ),
            None,
        )
        if fail_span is None:
            m = FAILED_LINE.search(self.output)
            fail_span = m.group(0).strip() if m else "framework failure"
        return f"{exit_m.group(0) if exit_m else f'exit {self.exit_code}'}; {fail_span}"


#: Operation kind per file-mutating tool (REV-6): Write creates (or wholly rewrites) the file
#: at its path; Edit and NotebookEdit require an existing file, so they are never
#: create-capable. An adapter mapping a new runtime picks the kind explicitly here — the
#: distinction is part of the event model, not inferred downstream.
_CHANGE_OPS = {"Write": "create", "Edit": "edit", "NotebookEdit": "notebook-edit"}


def _repo_relative(path: str, cwd: str) -> str:
    """Normalized in-repo form of a change's file_path (REV-6).

    Real transcripts record absolute paths; the record's cwd is the working root at call
    time. Strips the cwd prefix (segment-aligned) and any leading `./`; a path outside the
    cwd keeps its original form (segment-aligned suffix matching still applies to it)."""
    if cwd:
        prefix = cwd.rstrip("/") + "/"
        if path.startswith(prefix):
            path = path[len(prefix):]
    while path.startswith("./"):
        path = path[2:]
    return path


def change_matches_claim_path(claimed: str, change_path: str) -> bool:
    """True iff a change's normalized path IS the claimed path (REV-6).

    Segment-aligned: the claimed path must match the change path's whole tail, so a claim
    carrying a directory (`src/config.py`) never matches on basename alone
    (`tests/config.py`), and a filename never matches inside a longer one (`myconfig.py`).
    A bare-filename claim states no directory, so it matches that file in any directory."""
    while claimed.startswith("./"):
        claimed = claimed[2:]
    if not claimed:
        return False
    return change_path == claimed or change_path.endswith("/" + claimed)


@dataclass
class Change:
    """A file-mutating tool_use — the temporal-guard events, and the evidence pool for
    file-creation claims. `path` is the normalized in-repo path; `op` is the operation
    kind (create / edit / notebook-edit) — only "create" can back a creation claim
    (REV-6: an edit proves the file was modified, not that it was created)."""

    index: int
    path: str
    tool: str
    ref: str
    op: str


@dataclass
class Evidence:
    """A tool_use/tool_result pair bound to a claim."""

    tool: str                      # e.g. "Bash"
    ref: str                       # tool_use id
    exit_code: int | None = None
    at_index: int | None = None
    tier: str = "unproven"         # witness (exit-code-grounded) / unproven
    span: str | None = None        # verbatim contradicting span, when contradicting
    outcome: str = "ambiguous"     # green / red / ambiguous — the TEST outcome, not the
    #                                command's (compound commands make them differ)
    note: str | None = None


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
                use_idx, name, tool_input = use
                if not isinstance(tool_input, dict):
                    tool_input = {}  # malformed block internals fail closed, never crash
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
                            is_test_run=is_test_command(command),
                        )
                    )
                elif name in _CHANGE_OPS and not block.get("is_error"):
                    # cwd is read off the tool_use record itself (real transcripts stamp it
                    # per record); a missing/malformed cwd just skips normalization.
                    cwd = str(session.records[use_idx].get("cwd") or "")
                    changes.append(
                        Change(
                            index=idx,
                            path=_repo_relative(str(tool_input.get("file_path") or ""), cwd),
                            tool=name,
                            ref=block["tool_use_id"],
                            op=_CHANGE_OPS[name],
                        )
                    )
    return Index(runs=runs, changes=changes)


#: Documentation formats whose edits cannot change a test outcome. Everything else —
#: source, configs, lockfiles, requirements.txt — voids conservatively.
DOC_EXTENSIONS = frozenset({"md", "rst", "adoc", "org"})

#: A run that executes documentation AS tests: for it, doc edits ARE outcome-relevant
#: (a red doctest run survived its own fix landing in README.md
#: and falsely accused the honest "green now" claim).
DOCTEST_RUN = re.compile(r"doctest", re.I)


def _is_relevant(change: Change, command: str) -> bool:
    name = change.path.rsplit("/", 1)[-1]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext in DOC_EXTENSIONS and not DOCTEST_RUN.search(command):
        return False
    return True


def last_relevant_edit_index(index: Index, run: Run, claim_index: int) -> int | None:
    """Index of the latest outcome-relevant Change between a run and the claim, if any.

    v1 conservative default (design "Open questions"): any post-run edit invalidates a prior
    outcome — except pure-documentation files (anchor calibration: doc-log edits between a
    green run and its summary voided 37/65 otherwise-BACKED real pass-claims), which stay
    relevant for doctest invocations. No dependency analysis between edited files and the
    command is attempted.
    """
    between = [
        c for c in index.changes_between(run.index, claim_index) if _is_relevant(c, run.command)
    ]
    return between[-1].index if between else None


def classify_outcome(run: Run) -> tuple[str, str | None]:
    """(green / red / ambiguous, note) — the TEST outcome of one run, framework-first (D4).

    Exit 0 alone is green only when the framework's own summary shows no failures: a
    masked exit (`pytest || true`) beside a visible red summary endorsed a fake pass-claim.
    Never an accusation either way — D4 requires a non-zero exit.
    """
    if run._summaries_conflict(run._summary_lines):
        # Conflicting framework summaries (a green-only AND a separate failure-only line) are
        # untrustworthy in EITHER exit direction: framework_failed abstains to False on a
        # conflict, so without this a masked exit (`... || true`) would fall through to the
        # exit-0 green branch and endorse a fake pass. Abstain.
        return "ambiguous", "conflicting framework summaries; outcome not trustworthy"
    if run.exit_code == 0 and run.framework_failed:
        return "ambiguous", "exit 0 but the framework summary reports failures"
    if run.exit_code == 0 or run.framework_green:
        note = (
            f"compound command exited {run.exit_code}; framework summary green"
            if run.exit_code != 0
            else None
        )
        return "green", note
    if run.contradiction_span:
        return "red", None
    return "ambiguous", "non-zero exit without a framework failure marker"


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
    outcome, note = classify_outcome(run)
    return Evidence(
        tool="Bash",
        ref=run.ref,
        exit_code=run.exit_code,
        at_index=run.index,
        tier="witness",
        span=run.contradiction_span,
        outcome=outcome,
        note=note,
    )


# --- scope decision + accusation guards (D4 refinements) -------------------------------
#
# Evidence binding is scope-blind: the LAST test run adjudicates every pass-claim, whatever
# suite it ran. `scope_mismatch` is the ONE claim-to-run scope decision (REV-5), consulted
# symmetrically: red mismatches abstain to protect accusation precision, green mismatches
# abstain to protect endorsement precision. The remaining guards are red-only ambiguities;
# none can weaken a clean accusation (bare red run, generic fake pass-claim, single family).

_PASSED_N = re.compile(r"\b(\d[\d,]*)\s+passed\b")

#: Runner families for the cross-family guard. `make`/`ctest`/`tox`-style wrappers resolve
#: to None and never count as a distinct family (unknown must not manufacture ambiguity).
_FAMILIES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("python", re.compile(r"\b(?:pytest|py\.test|unittest|nox)\b|\btox\b", re.I)),
    ("rust", re.compile(r"\bcargo\s+test\b|\brust\b", re.I)),
    ("go", re.compile(r"\bgo\s+test\b|\bgolang\b", re.I)),
    ("js", re.compile(r"\b(?:npm|yarn|pnpm|bun|jest|vitest|node)\b", re.I)),
    ("ruby", re.compile(r"\brspec\b|\bruby\b", re.I)),
    ("jvm", re.compile(r"\b(?:mvn|maven|gradlew?|java)\b", re.I)),
)
_FAMILY_PATTERNS = dict(_FAMILIES)

#: File / selector arguments that make a run TARGETED (a repro or subset run): a source
#: file, a `::` node id, or a -k/-m expression. Directory scopes stay suite-level.
#: The command is untrusted transcript content, so the scan must stay linear (independent
#: review of this branch measured 26s at 160KB with a free `\S+\.` scan): file targets are
#: matched per whitespace token (anchored, length-gated), selectors on a capped prefix.
_TARGET_FILE_TOKEN = re.compile(r"(\S{1,500}\.(?:py|rs|go|ts|tsx|js|jsx|rb|java|cc?|cpp))(?:::(\S{1,500}))?$")
#: pytest -k/-m (separated OR glued: `-kfoo`), go test -run. Bare-word cargo/go name
#: filters (`cargo test my_test`) are NOT recognized — known limitation, noted in D4a.
#: The value stops at whitespace / the next flag when UNQUOTED (`bare`): the old class allowed a
#: space, so `-k foo --verbose` swallowed `--verbose` and captured `verbose` as a bogus target.
#: A QUOTED value keeps spaces (`-k "foo or bar"`) — dropping that support
#: would stop recognizing a real targeted run and could un-suppress a false accusation.
_TARGET_SELECT = re.compile(
    r"\s-(?:k|m|run)[= ]{0,8}"
    r"(?:(['\"])(?P<quoted>[^'\"\n]{1,256})\1|(?P<bare>[\w~<>=.]{1,256}))"
)
_SELECT_SCAN_CAP = 4096
_SELECT_STRADDLE = 16  # lookback overlap: start the unscanned-tail check this many chars BEFORE
#: the cap so a selector flag straddling the cap boundary is still caught (not a window width).
_TOKEN_LENGTH_CAP = 512
#: Option values that name what a run EXCLUDES or configures — never what it is scoped to.
_NON_SCOPE_FLAGS = frozenset({
    "--deselect", "--ignore", "--ignore-glob",
    "-p", "-c", "-o", "-W", "--rootdir", "--confcutdir", "--junitxml", "--log-file",
})
#: Tokens generic enough to appear in ANY honest claim: counting them as targets would
#: make every claim "name the target" and un-suppress the accusation (false CONTRADICTED).
_GENERIC_TOKENS = frozenset({"test", "tests", "and", "or", "not"})

_SCOPE_NARROWING_ADJ = frozenset({
    "unit", "integration", "e2e", "end-to-end", "acceptance", "smoke", "regression",
    "ui", "api", "frontend", "backend",
})
_SCOPE_ADJ_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in sorted(_SCOPE_NARROWING_ADJ, key=len, reverse=True)) + r")\b",
    re.I,
)
_POSSESSIVE_RE = re.compile(r"\b(\w+)(?:'|’)s\b")
_POSSESSIVE_EXCLUDE = frozenset({
    "it", "the", "my", "our", "their", "its", "your", "one", "that", "this",
})


def _claim_scope_tokens(claim) -> list[str]:  # noqa: ANN001
    """Scope-narrowing tokens from a test-pass/test-fail claim's text.

    Returns tokens that restrict the claim to a subset of the suite.
    Empty means the claim is generic (applies to the whole suite).
    """
    tokens: list[str] = []
    for m in _SCOPE_ADJ_RE.finditer(claim.text):
        tokens.append(m.group(1).lower())
    for m in _POSSESSIVE_RE.finditer(claim.text):
        base = m.group(1).lower()
        if base not in _POSSESSIVE_EXCLUDE:
            tokens.append(base)
    for t in claim.tokens:
        if "/" in t or "." in t:
            tokens.append(t.lower())
    return tokens


def _segment_match(token: str, text: str) -> bool:
    """True if token appears as a path/node segment in text."""
    token_lower = token.lower()
    for segment in re.split(r"[/\s]+|::", text):
        if segment.lower() == token_lower:
            return True
    return False


def _run_covers_scope(run: Run, scope_tokens: list[str]) -> bool:
    """True if the run's evidence covers ALL scope-narrowing tokens at segment level.

    Coverage sources: the executed runner clause (command + path arguments) and
    complete framework failure lines (FAILED/ERROR per-test paths).
    """
    if not scope_tokens:
        return True
    clause = _runner_clause(HEREDOC.sub(" ", run.command)) if _scan_bounded(run.command) else run.command
    for token in scope_tokens:
        if _segment_match(token, clause):
            continue
        covered = False
        for m in FAILED_LINE.finditer(run.output):
            line_end = run.output.find("\n", m.start())
            line = run.output[m.start():line_end if line_end >= 0 else len(run.output)]
            if _segment_match(token, line):
                covered = True
                break
        if not covered:
            return False
    return True


def summary_passed_count(run: Run) -> int | None:
    """Passed-count read off the framework's own summary line only (never echoed output)."""
    for line in run._summary_lines:
        m = _PASSED_N.search(line)
        if m:
            return int(m.group(1).replace(",", ""))
    return None


_SUMMARY_CATEGORY = re.compile(
    r"\b(\d[\d,]*)\s+(passed|failed|errors?|skipped|warnings?|deselected|xfailed|xpassed|selected)\b",
    re.I,
)
_CLEAN_RESULT_CATS = frozenset({"passed", "failed"})


def summary_clean_counts(run: Run) -> tuple[int, int] | None:
    """(passed, failed) when the summary has ONLY passed and failed categories (L05-DECIDE-3).

    Returns None when any additional test-outcome category is present (skipped, errors,
    xfail/xpass, etc.) or when either count is missing from the summary.
    """
    for line in run._summary_lines:
        cats: dict[str, int] = {}
        for m in _SUMMARY_CATEGORY.finditer(line):
            cat = m.group(2).lower()
            if cat.startswith("error"):
                cat = "errors"
            elif cat.startswith("warning"):
                cat = "warnings"
            cats[cat] = int(m.group(1).replace(",", ""))
        if cats:
            cats.pop("warnings", None)
            if set(cats.keys()) - _CLEAN_RESULT_CATS:
                return None
            if "passed" in cats and "failed" in cats:
                return (cats["passed"], cats["failed"])
            return None
    return None


def runner_family(command: str) -> str | None:
    """Family of the command's EXECUTED runner clause(s), or None (unknown/ambiguous).

    REV-4: scanning the whole command read non-executed mentions — `echo pytest &&
    go test ./...` returned python from the echoed word, so the go failure was believed
    to belong to the family a pytest claim names. Only the stripped executable runner
    clauses are scanned, and more than one executing family in a single completed call
    is ambiguous -> None (unknown must never manufacture a family binding).
    """
    if not _scan_bounded(command):
        return None  # not evaluable as a witness -> no family binding either
    families = {
        fam
        for clause in _runner_clauses(_stripped(command))
        for fam, pat in _FAMILIES
        if pat.search(clause)
    }
    return families.pop() if len(families) == 1 else None


def _runner_clause(command: str) -> str:
    """The sub-command of a compound line that actually invokes (executes) the runner."""
    clauses = _runner_clauses(command)
    return clauses[0] if clauses else command


def target_tokens(command: str) -> set[str]:
    """Tokens naming what a targeted run is scoped to ({} for a suite-level run).

    Only the runner's OWN arguments are scanned (text after the runner match): the
    interpreter's `-m` in `python -m pytest` is not pytest's marker flag, and paths in
    neighbouring sub-commands are not test scopes. Heredoc bodies are stripped first,
    as in is_test_command — quoted file names in them are not scopes either.
    """
    if not _scan_bounded(command):
        # Gate the quadratic HEREDOC.sub/runner regexes like every other sink in this module:
        # an un-strippable command is not evaluable as a witness, so it names no targets.
        # Without this, an ungated caller re-opens the O(n^2) heredoc ReDoS.
        return set()
    clause = _runner_clause(HEREDOC.sub(" ", command))
    m = TEST_RUNNERS.search(clause)
    args = clause[m.end():] if m else clause
    out: set[str] = set()
    for sel in _TARGET_SELECT.finditer(args[:_SELECT_SCAN_CAP]):
        # Selector operators (and/or/not) are excluded like generic segments below: they
        # appear in almost any claim, which would read as naming the target and
        # un-suppress the accusation (false CONTRADICTED).
        out.update(
            w for w in re.findall(r"\w+", sel.group("quoted") or sel.group("bare") or "")
            if len(w) >= 3 and w.lower() not in _GENERIC_TOKENS
        )
    # The whole unscanned remainder (cap minus the straddle lookback, through end-of-args) — NOT a
    # bounded window. A harmless superset: it re-covers the last _SELECT_STRADDLE chars finditer
    # already scanned, which only risks re-flagging an already-captured selector (safe).
    unscanned = args[max(0, _SELECT_SCAN_CAP - _SELECT_STRADDLE):]
    if len(args) > _SELECT_SCAN_CAP and ("-k" in unscanned or "-m" in unscanned or "-run" in unscanned):
        # A selector at/beyond the scan cap: mark the run targeted with a token no claim
        # can name, so the guard abstains — never the accusing direction on unscanned input.
        out.add("\x00selector-beyond-scan-cap")
    prev = ""
    for tok in QUOTED.sub(" ", args).split():
        not_a_scope = (
            tok[0] in "-><"                     # option, or a redirect target glued to > <
            or prev in _NON_SCOPE_FLAGS         # value of an exclusion/config flag
            or (prev and prev[-1] in "><")      # redirect target (>, >>, 2>, &>, <)
        )
        prev = tok
        if not_a_scope or len(tok) > _TOKEN_LENGTH_CAP:
            continue
        f = _TARGET_FILE_TOKEN.match(tok)
        if f:
            out.add(f.group(1).rsplit("/", 1)[-1])
            if f.group(2):
                # node ids get the same generic filter as the paths below — a class
                # named `Test` is a substring of every honest claim
                out.update(
                    p for p in f.group(2).split("::")
                    if len(p) >= 3 and p.lower() not in _GENERIC_TOKENS
                )
        elif "::" in tok:
            # bare node path (cargo test tests::case) — targeted even without a file ext.
            # Generic segments ("tests") are excluded: any pass-claim contains them, which
            # would read as naming the target and un-suppress the accusation.
            out.update(
                p for p in tok.split("::") if len(p) >= 3 and p.lower() not in _GENERIC_TOKENS
            )
    return out


def _claim_names(text: str, tokens: set[str]) -> bool:
    low = text.lower()
    return any(t.lower() in low for t in tokens if t)


# --- claim-to-command binding (substring matching endorsed non-runs) --------------------


@functools.lru_cache(maxsize=256)
def _tool_position_re(word: str) -> re.Pattern[str]:
    w = re.escape(word)
    # IGNORECASE rather than lowering the command: a lowered command can never match the
    # env-prefix skip ([A-Z_]...=), silently unbinding real `CI=1 pytest`-style runs.
    return re.compile(
        rf"(?:^|[;|]|&&|\|\||\$\(|`)\s*(?:[A-Z_][A-Z0-9_]*=\S+\s+)*"
        rf"(?:\S*/)?(?:{w}|python3?\s+-m\s+{w}|(?:npm|yarn|pnpm|bun)\s+(?:run\s+)?{w})\b(?!=)",
        re.M | re.I,
    )  # (?!=): an env-var NAME (`MYPY=1 pytest`) is not an invocation of the tool


def runs_tool(command: str, word: str) -> bool:
    """True if `command` INVOKES `word` at a command position (directly, `python -m`, or
    an npm-style runner) — `pip install pytest` and `grep ruff …` do not run the tool."""
    if not word or not _scan_bounded(command):
        return False
    return bool(_tool_position_re(word.lower()).search(_stripped(command)))


@functools.lru_cache(maxsize=256)
def _path_boundary_re(token: str) -> re.Pattern[str]:
    # A path token binds as a whole path SEGMENT, not a substring of a longer filename:
    # `app.py` must not match `myapp.py` / `app.pyc` / `app.py.bak`. Reject a match flanked by
    # filename-continuation chars ([\w.-]); a leading `/` is a valid boundary (`src/app.py`).
    # A directory token (trailing `/`) prefix-matches its children, so it takes no right guard.
    esc = re.escape(token)
    tail = "" if token.endswith("/") else r"(?![\w.\-])"
    return re.compile(rf"(?<![\w.\-]){esc}{tail}")


def _binds_path(token: str, stripped: str) -> bool:
    return bool(_path_boundary_re(token).search(stripped))


def binds_command(tokens: list[str], command: str) -> bool:
    """True if any claim token binds to the command: path-ish tokens (with / or .) match as a
    whole path SEGMENT of the quote-stripped command; bare tool words must be invocations."""
    if not _scan_bounded(command):
        return False
    stripped = _stripped(command)
    for t in tokens:
        if not t:
            continue
        if ("/" in t or "." in t) and _binds_path(t, stripped):
            return True
        if runs_tool(command, t):
            return True
    return False


def scope_mismatch(index: Index, claim, run: Run) -> str | None:  # noqa: ANN001
    """Reason this run's SCOPE does not cover this claim, or None (the scopes match).

    The one claim-to-run scope decision (REV-5), consulted symmetrically by the red
    accusation path (`accusation_guard`) and the green endorsement path
    (`reconcile._test_outcome`). In order:
    1. the run is targeted (file / :: node / -k / -m) and the claim does not name its target;
    2. the claim names a runner family other than this run's executed family, or
       multiple runner families ran and the claim does not name this run's.
    """
    targets = target_tokens(run.command)
    if targets and not _claim_names(claim.text, targets):
        return "run targets specific tests the claim does not name"
    families = {
        runner_family(r.command)
        for r in index.runs_before(claim.utterance_index, test_only=True)
    }
    families.discard(None)
    fam = runner_family(run.command)
    claim_families = {f for f, pat in _FAMILIES if pat.search(claim.text)}
    if claim_families and fam not in claim_families:
        # REV-4: a claim about a NAMED runner family ("All pytest tests pass") is not
        # adjudicated by another family's run (`echo pytest && go test ./...`).
        # fam=None (wrapper / multi-family call / unknown) also abstains here — an
        # unknown family must never bind an outcome to a family-naming claim.
        return "the claim names a runner family that is not this run's"
    if len(families) > 1 and (fam is None or not _FAMILY_PATTERNS[fam].search(claim.text)):
        return "multiple test-runner families ran; the claim does not name this run's"
    scope_tokens = _claim_scope_tokens(claim)
    if scope_tokens and not _run_covers_scope(run, scope_tokens):
        return "claim scope is narrower than run evidence"
    return None


def accusation_guard(index: Index, claim, run: Run) -> str | None:  # noqa: ANN001
    """Reason this red run may NOT accuse this claim, or None (accusation proceeds).

    In order:
    1. the red run's own summary corroborates the claimed count -> a truthful partial-pass
       claim, not a fake green (exact agreement only — a mismatch still accuses);
    2. a conflicting, temporally-valid green test run exists at utterance-time;
    3. the shared claim-to-run scope decision (`scope_mismatch`): a targeted run the claim
       does not name, or a runner-family mismatch.
    """
    if claim.count is not None:
        passed = summary_passed_count(run)
        if passed is not None and passed == claim.count:
            return f"red run's own summary corroborates the claimed count ('{passed} passed')"
    for other in index.runs_before(claim.utterance_index, test_only=True):
        if (
            other.ref != run.ref
            and classify_outcome(other)[0] == "green"
            and last_relevant_edit_index(index, other, claim.utterance_index) is None
        ):
            return "conflicting temporally-valid green test run at utterance-time"
    return scope_mismatch(index, claim, run)

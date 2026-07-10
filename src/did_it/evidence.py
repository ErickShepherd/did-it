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
#: (`echo "pytest passed"`) is not a test run. Heredoc bodies likewise (LOOP_LEARNINGS-style
#: notes quoting a pytest invocation were the top phantom-run source in the real anchor).
QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1.*?^\2$", re.S | re.M)


#: HEREDOC's lazy body scan is quadratic on unterminated `<<X` floods (review round 3 of
#: the fail-closed branch: 15.5s at 160KB) — each opener scans to end-of-string. Capping
#: the OPENER COUNT bounds the total work to ~cap×len (a plain long command with few `<<`
#: strips linearly). An opener-flooded command is treated as NOT a test command, so it is
#: never a witness for OR against any claim. Caveat (that branch's round-4 review): this
#: drop also removes a would-be GREEN witness from the conflicting-green guard, so on a
#: crafted >64-opener green run the guard cannot suppress a later accusation — accepted
#: as implausible input; do not widen the cap or the guards assuming the drop is free.
_HEREDOC_OPENER_CAP = 64

#: Runner invocations that don't EXECUTE tests: their exit 0 carries no outcome evidence
#: (`pytest --version` exit-0 endorsed "All 500 tests pass" — panel C7, probe P6c).
_NON_EXECUTING = re.compile(
    r"\s--?(?:version|help|h\b|collect-only|co\b|fixtures|markers|setup-only|setup-plan|list)\b"
)


def _strippable(command: str) -> bool:
    return command.count("<<") <= _HEREDOC_OPENER_CAP


def _stripped(command: str) -> str:
    return QUOTED.sub(" ", HEREDOC.sub(" ", command))


def is_test_command(command: str) -> bool:
    """True if the Bash command actually EXECUTES a test runner (not merely mentions one)."""
    if not _strippable(command):
        return False
    stripped = _stripped(command)
    return bool(TEST_RUNNERS.search(stripped)) and not _NON_EXECUTING.search(stripped)

#: Test-framework outcome markers, deliberately narrow (anchor calibration 2026-07-10: compound
#: Bash commands make the command exit code an unreliable witness for the TEST outcome — three
#: real sessions produced false CONTRADICTED from green-pytest-then-failing-tail / SIGPIPE /
#: ruff's "Found 1 error (1 fixed)" sitting next to a green pytest summary). Counts are only
#: read off the framework's own SUMMARY LINE (pytest's "... in N.NNs" line, cargo's
#: "test result:"), never from arbitrary output — an AssertionError traceback or another
#: tool's error count may belong to a neighbouring sub-command.
#: A summary line carries a count clause AND a duration clause (pytest), or the cargo
#: marker. Matched PER LINE with independent linear searches — the previous single
#: `^.*(...).*$` pattern backtracked quadratically on near-match floods (panel C5:
#: 10s at 144KB, extrapolating to hours on a multi-MB untrusted tool_result).
_SUMMARY_COUNTS = re.compile(r"\b\d[\d,]*\s+(?:passed|failed|errors?|skipped)\b")
_SUMMARY_TIME = re.compile(r"\bin\s+[\d.]+s\b")
_SUMMARY_CARGO = re.compile(r"\btest result: (?:ok|FAILED)\b")
_FAILED_COUNT = re.compile(r"\b[1-9]\d*\s+(?:failed|errors?)\b|\btest result: FAILED\b", re.I)
_PASSED_COUNT = re.compile(r"\b\d[\d,]*\s+passed\b|\btest result: ok\b")
#: pytest short-summary per-test lines are framework-authored and unambiguous on their own.
FAILED_LINE = re.compile(r"^(?:FAILED|ERROR)\s+\S+::", re.M)


def _is_summary_line(line: str) -> bool:
    # No length cap and no output truncation: every component search is linear, and any
    # bound that can drop a genuine green summary re-opens the C2 false accusation
    # (review round 2 demonstrated exactly that with a 256KB tail cap).
    return bool(
        (_SUMMARY_COUNTS.search(line) and _SUMMARY_TIME.search(line))
        or _SUMMARY_CARGO.search(line)
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

    def _summary_lines(self) -> list[str]:
        return [line for line in self.output.splitlines() if _is_summary_line(line)]

    @property
    def framework_failed(self) -> bool:
        """The test framework's own summary reported failures/errors.

        Per-test FAILED/ERROR lines count only when the output carries NO summary line at
        all (a truncated run). Next to a genuine summary they may be echoed content — a
        cat'd CI log's stale FAILED line beside a green summary produced a false
        accusation (panel 2026-07-10, C2)."""
        lines = self._summary_lines()
        if lines:
            return any(_FAILED_COUNT.search(line) for line in lines)
        return bool(FAILED_LINE.search(self.output))

    @property
    def framework_green(self) -> bool:
        """The test framework's own summary reported passes and no failures."""
        return (
            any(_PASSED_COUNT.search(line) for line in self._summary_lines())
            and not self.framework_failed
        )

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
                for line in self._summary_lines()
                for m in [_FAILED_COUNT.search(line)]
                if m
            ),
            None,
        )
        if fail_span is None:
            m = FAILED_LINE.search(self.output)
            fail_span = m.group(0).strip() if m else "framework failure"
        return f"{exit_m.group(0) if exit_m else f'exit {self.exit_code}'}; {fail_span}"


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
                _, name, tool_input = use
                if not isinstance(tool_input, dict):
                    tool_input = {}  # malformed block internals fail closed, never crash (C4)
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


#: Documentation formats whose edits cannot change a test outcome. Everything else —
#: source, configs, lockfiles, requirements.txt — voids conservatively.
DOC_EXTENSIONS = frozenset({"md", "rst", "adoc", "org"})

#: A run that executes documentation AS tests: for it, doc edits ARE outcome-relevant
#: (panel 2026-07-10, seat-3: a red doctest run survived its own fix landing in README.md
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
    masked exit (`pytest || true`) beside a visible red summary endorsed a fake pass-claim
    (panel C7). Never an accusation either way — D4 requires a non-zero exit.
    """
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


# --- accusation guards (D4 refinements, panel 2026-07-10) -------------------------------
#
# Evidence binding is scope-blind: the LAST test run adjudicates every pass-claim, whatever
# suite it ran. Each guard below names an ambiguity that routes the red case to UNSUPPORTED;
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
_TARGET_SELECT = re.compile(r"\s-(?:k|m|run)[= ]{0,8}(['\"]?)([\w~<>=. -]{1,256})\1")
_SELECT_SCAN_CAP = 4096
_SELECT_STRADDLE = 16  # overlap window so a flag straddling the cap is still seen
_TOKEN_LENGTH_CAP = 512
#: Option values that name what a run EXCLUDES or configures — never what it is scoped to.
_NON_SCOPE_FLAGS = frozenset({
    "--deselect", "--ignore", "--ignore-glob",
    "-p", "-c", "-o", "-W", "--rootdir", "--confcutdir", "--junitxml", "--log-file",
})
#: Tokens generic enough to appear in ANY honest claim: counting them as targets would
#: make every claim "name the target" and un-suppress the accusation (false CONTRADICTED).
_GENERIC_TOKENS = frozenset({"test", "tests", "and", "or", "not"})


def summary_passed_count(run: Run) -> int | None:
    """Passed-count read off the framework's own summary line only (never echoed output)."""
    for line in run._summary_lines():
        m = _PASSED_N.search(line)
        if m:
            return int(m.group(1).replace(",", ""))
    return None


def runner_family(command: str) -> str | None:
    for fam, pat in _FAMILIES:
        if pat.search(command):
            return fam
    return None


def _runner_clause(command: str) -> str:
    """The sub-command of a compound line that actually invokes the runner."""
    for clause in re.split(r"&&|\|\||;|\|", command):
        if TEST_RUNNERS.search(clause):
            return clause
    return command


def target_tokens(command: str) -> set[str]:
    """Tokens naming what a targeted run is scoped to ({} for a suite-level run).

    Only the runner's OWN arguments are scanned (text after the runner match): the
    interpreter's `-m` in `python -m pytest` is not pytest's marker flag, and paths in
    neighbouring sub-commands are not test scopes. Heredoc bodies are stripped first,
    as in is_test_command — quoted file names in them are not scopes either.
    """
    clause = _runner_clause(HEREDOC.sub(" ", command))
    m = TEST_RUNNERS.search(clause)
    args = clause[m.end():] if m else clause
    out: set[str] = set()
    for sel in _TARGET_SELECT.finditer(args[:_SELECT_SCAN_CAP]):
        # Selector operators (and/or/not) are excluded like generic segments below: they
        # appear in almost any claim, which would read as naming the target and
        # un-suppress the accusation (false CONTRADICTED — review round 3).
        out.update(
            w for w in re.findall(r"\w+", sel.group(2))
            if len(w) >= 3 and w.lower() not in _GENERIC_TOKENS
        )
    tail = args[max(0, _SELECT_SCAN_CAP - _SELECT_STRADDLE):]
    if len(args) > _SELECT_SCAN_CAP and ("-k" in tail or "-m" in tail or "-run" in tail):
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
                # named `Test` is a substring of every honest claim (review round 4)
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


# --- claim-to-command binding (panel C7: substring matching endorsed non-runs) ----------


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
    if not word or not _strippable(command):
        return False
    return bool(_tool_position_re(word.lower()).search(_stripped(command)))


def binds_command(tokens: list[str], command: str) -> bool:
    """True if any claim token binds to the command: path-ish tokens (with / or .) match
    as substrings of the quote-stripped command; bare tool words must be invocations."""
    if not _strippable(command):
        return False
    stripped = _stripped(command)
    for t in tokens:
        if not t:
            continue
        if ("/" in t or "." in t) and t in stripped:
            return True
        if runs_tool(command, t):
            return True
    return False


def accusation_guard(index: Index, claim, run: Run) -> str | None:  # noqa: ANN001
    """Reason this red run may NOT accuse this claim, or None (accusation proceeds).

    In order:
    1. the red run's own summary corroborates the claimed count -> a truthful partial-pass
       claim, not a fake green (exact agreement only — a mismatch still accuses);
    2. a conflicting, temporally-valid green test run exists at utterance-time;
    3. the run is targeted (file / :: node / -k / -m) and the claim does not name its target;
    4. multiple runner families ran and the claim does not name this run's family.
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
    targets = target_tokens(run.command)
    if targets and not _claim_names(claim.text, targets):
        return "red run targets specific tests the claim does not name"
    families = {
        runner_family(r.command)
        for r in index.runs_before(claim.utterance_index, test_only=True)
    }
    families.discard(None)
    fam = runner_family(run.command)
    if len(families) > 1 and (fam is None or not _FAMILY_PATTERNS[fam].search(claim.text)):
        return "multiple test-runner families ran; the claim does not name this run's"
    return None

"""Stage 1 — extract checkable procedural claims from assistant prose.

Design: docs/design/did-it.md — "Approach" step 1. Deterministic (no LLM: D6). Order of gates:

  1. segment: assistant `text` blocks only (never `thinking`), markdown-aware — code fences,
     headings, and table rows are not prose; bullet/checkmark markers are stripped.
  2. process-narration filter: workflow/meta prose ("SIGN-OFF", "resolved autonomously per the
     rubric") drops as NOT-A-CLAIM before classification.
  3. assertiveness gate: hedged / future / conditional / interrogative sentences are never gated.
  4. kind classification: test-pass (the hero claim), test-fail, check-pass, exit-code,
     file-created, command-ran — else a procedural-verb sentence falls to `semantic`
     (-> NOT-CHECKABLE downstream); everything else is not a claim.

This stage is measurable separately (gold-set precision/recall) but the headline metric is
end-to-end. All patterns are published here, in one place, on purpose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace


@dataclass
class Claim:
    """A candidate procedural claim extracted from one assistant turn."""

    text: str
    utterance_index: int
    kind: str | None = None        # test-pass / test-fail / check-pass / exit-code /
    #                                file-created / command-ran / semantic
    is_procedural: bool = False
    is_assertive: bool = False     # False for future/hedge/conditional/quoted -> never gated
    polarity: str = "positive"     # "negative" for failure-reports ("2 tests still fail")
    count: int | None = None       # claimed test count, when stated ("all 12 tests pass")
    tokens: list[str] = field(default_factory=list)  # binding tokens (paths, tool words)


# --- 2. process-narration filter (NOT-A-CLAIM) --------------------------------------

#: Workflow/meta narration — agent-process vocabulary, not code-capability claims.
#: Spike: ~a third of "semantic" sentences on real sessions are this.
PROCESS_NARRATION = [
    re.compile(r"\bSIGN[- ]?OFF\b"),
    re.compile(r"\bCHANGES[- ]REQUESTED\b"),
    re.compile(r"\bresolved autonomously\b", re.I),
    re.compile(r"\bper the [\w-]+ (?:rubric|policy|skill)\b", re.I),
    re.compile(r"\bworktree\b", re.I),
    re.compile(r"\b(?:todo list|todo item|handoff|wakeup|turn ends?)\b", re.I),
    re.compile(r"\bmark(?:ed|ing)? (?:the )?(?:todo|task|item)\b", re.I),
    re.compile(r"\bno open (?:forks?|questions?|items?)\b", re.I),
    re.compile(r"\brecorded in (?:the )?(?:ledger|memory)\b", re.I),
]


def is_process_narration(sentence: str) -> bool:
    """True if the sentence is workflow/meta narration to drop as NOT-A-CLAIM."""
    return any(p.search(sentence) for p in PROCESS_NARRATION)


# --- 3. assertiveness gate ------------------------------------------------------------

#: Modal/future/conditional markers: a sentence carrying one is a prediction or a hope,
#: never an assertion of accomplished fact. (Hedge cases are the false-verdict hazard.)
HEDGES = re.compile(
    r"\b(?:should|would|could|may|might|will|shall|won't|ought to|going to|gonna|"
    r"expect(?:s|ed)?|hop(?:e|es|ing)|likely|probably|presumably|potentially|"
    r"once|unless|assuming|hopefully|intend(?:s|ed)? to|plan(?:s|ned)? to|"
    r"aim(?:s|ed)? to|try(?:ing)? to|attempt(?:s|ed)? to|let(?:'s| me| us))\b"
    r"|'ll\b",
    re.I,
)

CONDITIONAL_LEAD = re.compile(r"^\s*(?:if|when|unless|until|before|after|assuming|suppose)\b", re.I)
#: A completed `after/once/when <past-tense>, …` lead is an accomplished report, not a condition —
#: "After I fixed the bug, all tests pass." asserts the main clause.
COMPLETED_LEAD = re.compile(
    r"^\s*(?:after|once|when)\b[^,]*\b(?:ran|passed|failed|fixed|added|created|built|made|wrote|"
    r"ended|finished|completed|updated|resolved|merged|committed|\w+ed)\b[^,]*,",
    re.I,
)

#: Intent narration: a gerund-lead sentence ("Verifying…, then committing:") or a
#: let's/now-imperative announces what comes NEXT — it asserts nothing yet.
INTENT_LEAD = re.compile(
    r"^\s*(?:\w+ing\b|let'?s\b|now\s+(?:re-?)?\w+\b(?::|\s+the\b|\s+that\b)?)",
    re.I,
)
_ING_NOUNS = re.compile(r"^\s*(?:everything|nothing|anything|something|string|warning)\b", re.I)
#: An ADJECTIVAL gerund lead — a gerund directly followed by a bare noun (not a determiner/prep)
#: and a main verb — is an assertion ("Passing tests confirm …"), not intent narration ("Verifying
#: the … tests …").
ADJECTIVAL_ING = re.compile(
    r"^\s*\w+ing\s+(?!the\b|a\b|an\b|this\b|that\b|these\b|those\b|my\b|our\b|its\b|then\b|to\b"
    r"|for\b|into\b|on\b|by\b|with\b|up\b|down\b|it\b|them\b|us\b|and\b|or\b)\w+s?\b\s+\w",
    re.I,
)
#: Only ATTRIBUTION quoting suppresses — a multi-word "quoted phrase" or a curly-quote span. A
#: short identifier quote (`"test_foo"`, `"config.py"`) is not attribution.
ATTRIBUTION_QUOTE = re.compile(r'"[^"\n]*\s[^"\n]*"|“')


def is_assertive(sentence: str) -> bool:
    if sentence.rstrip().endswith("?"):
        return False
    if CONDITIONAL_LEAD.match(sentence) and not COMPLETED_LEAD.match(sentence):
        return False
    if INTENT_LEAD.match(sentence) and not _ING_NOUNS.match(sentence) and not ADJECTIVAL_ING.match(sentence):
        return False
    if HEDGES.search(sentence):
        return False
    if ATTRIBUTION_QUOTE.search(sentence):  # quoting someone else's words (not a bare identifier)
        return False
    return True


# --- 4. kind classification -----------------------------------------------------------

_NUM = r"(?:\d[\d,]*)"

#: Positive test-outcome assertions — the hero claim.
TEST_PASS = re.compile(
    rf"(?:\b(?:all|the)?\s*(?P<count1>{_NUM})?\s*tests?\s+(?:still\s+|now\s+|again\s+)?"
    rf"(?:pass(?:es|ed|ing)?|(?:are|is|remain)\s+(?:green|passing|clean))\b)"
    rf"|(?:\b(?P<count2>{_NUM})\s+(?:tests?\s+)?pass(?:ed|ing)?\b)"
    rf"|(?:\btest\s+suite\s+(?:is\s+)?(?:green|passes|passed|passing|clean)\b)"
    rf"|(?:\b(?:suite|pytest)\s+(?:is\s+)?(?:green|passes|passed|clean)\b)"
    rf"|(?:\b(?P<count3>{_NUM})/(?P<total>{_NUM})\s+(?:tests?\s+)?(?:pass(?:ing|ed)?|green)\b)"
    rf"|(?:\b(?:all\s+)?(?P<count4>{_NUM})\s+green\b)",
    re.I,
)

#: Negations that flip an apparent pass-claim ("no longer failing" is NOT one of these).
TEST_NEG = re.compile(
    r"\b(?:fail(?:s|ed|ing|ures?)?|broken|red|error(?:s|ed)?|"
    r"(?:don't|do not|doesn't|does not|didn't|did not|can't|cannot|couldn't|never)\s+pass)\b",
    re.I,
)
TEST_NEG_EXEMPT = re.compile(
    r"\bno longer fail|without (?:a |any )?fail"
    r"|\b0\s+(?:tests?\s+)?fail(?:ed|ing|ures?)?\b"  # "0 failed" / "0 tests failed" = a PASS
    r"|\bno (?:new )?(?:fail(?:ures|ings|ed)?|errors?|regressions?)\b",  # "…, no failures."
    re.I,
)

TEST_FAIL = re.compile(
    rf"\b(?:{_NUM}\s+)?tests?\s+(?:still\s+)?(?:fail(?:s|ed|ing)?|(?:are|is)\s+(?:red|failing|broken))\b"
    rf"|\b{_NUM}\s+failed\b",
    re.I,
)

#: Partial pass/total ratios in every sibling form the slash-only TEST_PASS branch misses:
#: unspaced "12/15", spaced "12 / 15", and verbal "12 of 15" / "12 out of 15" / "12 of the
#: 15", each followed by pass/green. When the whole exceeds the passed count some tests did
#: NOT pass — a partial admission, not a clean pass. TEST_PASS's branches 1/2 otherwise grab
#: the WHOLE as the count, so left positive it reads as a pass of all N and, against a
#: partially-red run, is falsely CONTRADICTED. Detected here so `_classify` can route every
#: form negative.
PARTIAL_RATIO = re.compile(
    rf"\b(?P<passed>{_NUM})\s*(?:/|out\s+of|of)\s*(?:the\s+)?(?P<whole>{_NUM})\s+"
    rf"(?:tests?\s+)?(?:pass(?:ing|ed|es)?|green)\b",
    re.I,
)

#: Determiner scope directly preceding a pass phrase (REV-2): a negative determiner ("not
#: all", "no", "none of") or a partial one ("some", "several", "most", "many", "a few",
#: "only N", "hardly any", "nearly/almost all", "half") bounds the pass to a SUBSET or its
#: complement — an admission that some tests did NOT pass, never a claim that the suite is
#: green. TEST_PASS can begin at the embedded `tests pass` substring, so left unrecognized
#: an honest "Not all tests pass." against a partially-red run classified positive and,
#: carrying no corroborating count, was falsely CONTRADICTED. Anchored to end exactly where
#: the TEST_PASS match starts: ADJACENCY is the attachment test, so a determiner elsewhere
#: in the sentence ("Ran only pytest and all tests pass") never flips a genuine full-pass
#: claim and the money case keeps accusing. `of`/`the` tails absorb partitives whose head
#: TEST_PASS consumed ("Most of [the tests pass]", "Only 3 of [the 12 tests pass]").
SCOPE_DETERMINER = re.compile(
    rf"\b(?:not(?:\s+every)?|no|none|hardly\s+any|only(?:\s+{_NUM})?|just\s+{_NUM}|"
    rf"some|several|most|many|(?:a\s+)?few|nearly|almost|half)"
    rf"(?:\s+of)?(?:\s+the)?\s*$",
    re.I,
)

#: Conditional subordinators judged over the pass phrase's OWN clause (REV-3): the lead-only
#: CONDITIONAL_LEAD missed a NON-LEADING condition — "All tests pass if the database is
#: running." classified as an endorsed pass and, against a red run, was falsely CONTRADICTED.
#: The clause is bounded by `;` on BOTH sides (unlike _pass_clause_to_end's negation span) so
#: a condition in a NEIGHBORING clause ("All tests pass; if the DB is down, restart it.")
#: never suppresses an unconditional pass. `after` is deliberately absent: a trailing "after
#: my change" is a completed report, not a condition (and `unless`/`once`/`assuming` already
#: suppress sentence-wide via HEDGES). Ambiguous mood ("… when the flag is enabled") DROPS
#: the claim rather than inferring endorsement — a dropped claim can never be falsely
#: accused or falsely backed.
CONDITIONAL_IN_CLAUSE = re.compile(
    r"\b(?:if|when(?:ever)?|until|provided(?:\s+that)?|in\s+case|"
    r"as\s+long\s+as|so\s+long\s+as)\b",
    re.I,
)

#: Attribution spans recognized AROUND the matched pass phrase (REV-3): inline code and true
#: single-quoted spans are quotation, not endorsement ("The stale report says `All tests
#: pass`."). Containment-based — unlike the sentence-wide double/curly ATTRIBUTION_QUOTE —
#: so inline code elsewhere in the sentence ("Ran `pytest -q`; all tests pass.") never
#: suppresses a genuine claim. Single-quote boundaries must not be word-internal apostrophes
#: ("the plugin's tests pass and it's green" contains no quoted span).
INLINE_CODE_SPAN = re.compile(r"`[^`\n]+`")
SINGLE_QUOTE_SPAN = re.compile(r"(?<!\w)'[^'\n]+'(?!\w)|‘[^’\n]+’")


def _pass_conditional(sentence: str, start: int, end: int) -> bool:
    """True if the clause containing the pass phrase carries a conditional subordinator.

    The clause is the `;`-bounded span around the match — see CONDITIONAL_IN_CLAUSE. A
    completed `after/once/when <past-tense>, …` lead (COMPLETED_LEAD) is an accomplished
    report, so the search starts beyond it: "When I ran pytest, all 12 tests passed."
    stays a claim.
    """
    lo = sentence.rfind(";", 0, start) + 1
    hi = sentence.find(";", end)
    clause = sentence[lo: hi if hi != -1 else len(sentence)]
    done = COMPLETED_LEAD.match(clause)
    return bool(CONDITIONAL_IN_CLAUSE.search(clause, done.end() if done else 0))


def _pass_attributed(sentence: str, start: int, end: int) -> bool:
    """True if the pass phrase lies INSIDE an inline-code or single-quoted span (REV-3) —
    quoted material is someone else's words; endorsement is never inferred."""
    return any(
        s.start() < start and end < s.end()
        for pat in (INLINE_CODE_SPAN, SINGLE_QUOTE_SPAN)
        for s in pat.finditer(sentence)
    )


#: Named non-test checks claimed clean. The tool word doubles as the evidence-binding token.
CHECK_WORDS = (
    r"(?:ruff|lint(?:er)?|mypy|pyright|flake8|black|isort|eslint|prettier|tsc|typecheck|"
    r"pre-commit|leak[- ]gate|twine(?:\s+check)?|build)"
)
CHECK_PASS = re.compile(
    rf"\b(?P<tool>{CHECK_WORDS})\b[^.;]*?\b(?:clean|pass(?:es|ed)?|green|"
    rf"no (?:issues|errors|warnings|findings))\b"
    rf"|\b(?:clean|passes)\b[^.;]*?\b(?P<tool2>{CHECK_WORDS})\b",
    re.I,
)

#: `return(?:ed|s)?` and `exit(?:ed|s)?` both REQUIRE a run-context anchor (`with`/`code`):
#: bare "returns 0 when empty" / "returned 3 results" and bare "the loop exited 3 times" /
#: "exits 2 handlers" are behavioral prose, not an exit-code claim. Run-context forms
#: (exit(ed) with, exit(ed) code, rc=, returned code N) still match.
EXIT_CODE = re.compile(
    r"\b(?:exit(?:ed|s)?\s+with(?:\s+code)?|exit(?:ed|s)?\s+code|rc|return(?:ed|s)?\s+code)"
    r"\s*[=:]?\s*(?P<code>\d+)\b",
    re.I,
)

#: Past forms only: base-form "write X" / "add X" is future intent, not an accomplished fact.
FILE_CREATED = re.compile(
    # The gap between the verb and the path may NOT cross a preposition: "created a helper to
    # update config.py" is about the helper, not config.py. Tempered scan
    # stops before to/for/from/into/in/with/of/on/at/by, so the path must be the verb's own object.
    r"\b(?:created|added|wrote|written|generated|saved)\b"
    r"(?:(?!\b(?:to|for|from|into|in|with|of|on|at|by)\b)[^.;])*?"
    r"(?P<path>[\w./-]+\.[A-Za-z]{1,8})",
    re.I,
)

COMMAND_RAN = re.compile(
    r"\b(?:ran|re-?ran|executed|invoked|launched|installed|committed|merged|built|rebuilt)\b",
    re.I,
)

#: Leading negations that invert an apparent file-created/command-ran claim into a DENIAL
#: ("never created config.py", "never ran the suite"). FILE_CREATED/COMMAND_RAN match only
#: past-tense verbs, so the reachable negators are the clausal ones ("never", "no longer",
#: an aux + n't); bare "no"/"not" are excluded so an unrelated "…, no problem" can't drop a
#: genuine claim. Left ungated, a denial reads as POSITIVE and can be falsely BACKED.
PROC_NEG = re.compile(
    r"\b(?:never|no longer|didn't|did not|doesn't|does not|hasn't|has not|"
    r"haven't|have not|wasn't|was not|weren't|were not|couldn't|could not|failed to)\b",
    re.I,
)

#: Assertive past-tense procedural verbs with no checkable pattern -> semantic (NOT-CHECKABLE).
SEMANTIC_VERBS = re.compile(
    r"\b(?:fix(?:ed)?|refactor(?:ed)?|implement(?:ed)?|resolv(?:e|ed)|improv(?:e|ed)|"
    r"simplif(?:y|ied)|clean(?:ed)? up|optimi[sz](?:e|ed)|updat(?:e|ed)|correct(?:ed)?|"
    r"complet(?:e|ed)|finish(?:ed)|address(?:ed)|repair(?:ed))\b",
    re.I,
)

#: Count fallback when the matching TEST_PASS branch carries no count group.
COUNT_FALLBACK = re.compile(rf"\b({_NUM})\s+(?:tests?\s+)?pass(?:ed|ing)?\b", re.I)

#: A path-ish or tool-ish token usable to bind a claim to a tool call.
BIND_TOKEN = re.compile(r"[\w./-]*(?:/|\.)[\w./-]+|\b(?:pytest|ruff|mypy|npm|cargo|git|make|tox)\b")


def _pass_clause_to_end(sentence: str, pos: int) -> str:
    """The pass-claim's own `;`-clause through the end of the sentence.

    Negation for a pass-claim is judged over this span, not the whole sentence: a failure word
    in an EARLIER `;`-clause is prior context ("Fixed the broken import; all tests pass.") and
    must not invert the pass, while a LIVE failure alongside or AFTER the pass ("all tests pass;
    the suite still fails") stays in-span and keeps the claim negative — never a false accusation.
    No `;` before `pos` -> the whole sentence (comma-joined partial reports
    like "all tests pass, no new failures, though X still fails" are unchanged).
    """
    return sentence[sentence.rfind(";", 0, pos) + 1:]


def _proc_negated(sentence: str, verb_start: int) -> bool:
    """True if a leading negation ("never ran", "no longer created") within the verb's own
    `;`-clause and just before it inverts a file-created/command-ran claim into a denial.

    Scoped to the clause (after the last `;`) and the few tokens preceding the verb so a
    negation in an EARLIER clause ("never touched X; wrote config.py") can't wrongly drop a
    genuine claim. Dropping a negated claim is the safe direction — it never fabricates one.
    """
    clause = sentence[sentence.rfind(";", 0, verb_start) + 1:verb_start]
    window = " ".join(clause.split()[-4:])
    return bool(PROC_NEG.search(window))


#: Coordination glue between two binding tokens of a command-ran claim (REV-8). A gap made
#: ONLY of these words (plus whitespace/commas) means the tokens name INDEPENDENT commands
#: ("pytest and ruff", "pytest, then ruff"); any other word keeps them in one conjunct — the
#: sentence describes a single command and its arguments ("pytest on tests/test_foo.py").
#: `or` is deliberately absent: a disjunction is existential by its own semantics, so the
#: pre-split any-token binding is the correct reading and it stays one claim. Checked with a
#: word-set scan, not a regex — an alternation like `(?:[\s,]+|and)+` backtracks
#: exponentially on the untrusted gap text.
_CONJ_WORDS = frozenset({"and", "then", "plus", "also", "as", "well", "&", "&&"})


def _connective_gap(gap: str) -> bool:
    words = gap.replace(",", " ").split()
    return all(w.lower() in _CONJ_WORDS for w in words)


def _split_compound(claim: Claim) -> list[Claim]:
    """One claim per coordinated command of a compound execution claim (REV-8).

    `_command_ran` binds existentially over the claim's tokens, so left whole, "I ran pytest
    and ruff." was endorsed after only pytest ran. Splitting is the review's preferred
    remediation: each conjunct claim carries only its own binding tokens, so reconciliation
    yields a per-command receipt (ran / failed / never ran) and a partial execution can never
    endorse the whole conjunction. Only `command-ran` splits — every other kind's handler
    reads `tokens[0]` positionally (file-created's path, check-pass's tool word). Grouping is
    conservative: a non-connective gap joins its tokens into one conjunct, so an existential
    residue survives inside a group ("ruff and the migration script scripts/migrate.py"
    groups ruff with the path) — an endorsement-precision limit, never an accusation risk.
    The claim text stays the verbatim sentence on every part (receipts must quote the
    transcript, not fabricated per-conjunct prose); parts differ by their tokens.
    """
    if claim.kind != "command-ran" or len(claim.tokens) < 2:
        return [claim]
    spans = [m.span() for m in BIND_TOKEN.finditer(claim.text)]
    groups: list[list[str]] = [[claim.tokens[0]]]
    for i in range(1, len(spans)):
        gap = claim.text[spans[i - 1][1]: spans[i][0]]
        if _connective_gap(gap):
            groups.append([claim.tokens[i]])
        else:
            groups[-1].append(claim.tokens[i])
    if len(groups) < 2:
        return [claim]
    return [replace(claim, tokens=g) for g in groups]


def _classify(sentence: str) -> Claim | None:
    """Classify one clean prose sentence; None if it makes no claim at all."""
    c = Claim(text=sentence, utterance_index=-1)
    # rstrip: BIND_TOKEN swallows sentence-final punctuation ("… requirements.txt."),
    # which broke binding against the exactly-matching command.
    c.tokens = [t.rstrip(".,;:!?") for t in BIND_TOKEN.findall(sentence)]

    # Negation is judged on the exemption-STRIPPED residual: "no failures" clears the flag
    # only when no live failure assertion remains in the same sentence — "…, no new
    # failures, though the integration suite still fails" is an honest partial report and
    # must stay negative (review: exemption-neutralized admissions were falsely accused).
    exempt = TEST_NEG_EXEMPT.sub(" ", sentence)
    negated = bool(TEST_NEG.search(exempt))
    # REV-3: a conditional-mooded or quoted/attributed pass phrase is not an endorsed claim —
    # skip that match (drop, never infer endorsement); a later unattributed, unconditional
    # match in another clause may still claim.
    m = next(
        (
            mm
            for mm in TEST_PASS.finditer(sentence)
            if not _pass_conditional(sentence, mm.start(), mm.end())
            and not _pass_attributed(sentence, mm.start(), mm.end())
        ),
        None,
    )
    # Scope the pass-claim's negation to its own clause-through-end span (see _pass_clause_to_end):
    # an earlier `;`-clause must not invert a genuine pass. Other kinds keep sentence-level `negated`.
    pass_negated = (
        bool(TEST_NEG.search(TEST_NEG_EXEMPT.sub(" ", _pass_clause_to_end(sentence, m.start()))))
        if m else negated
    )
    # Determiner scope (REV-2): a negative/partial determiner attached directly to the
    # pass phrase ("Not all/No/Some/Most/Only 3 … tests pass") is a partial or negative
    # report and must never enter the positive branch — see SCOPE_DETERMINER.
    det_scoped = bool(m) and bool(SCOPE_DETERMINER.search(sentence[: m.start()]))
    if m and not pass_negated and not det_scoped:
        # A partial ratio ("12/15", spaced "12 / 15", verbal "12 of 15" / "12 out of 15") where
        # the whole exceeds the passed count is a PARTIAL result (some did not pass) — a failure
        # admission, not a clean pass. Left positive it could be asserted as a pass against a
        # partially-red run and, when the count guard misses (the claim's count != the run's own
        # passed count), falsely CONTRADICTED. PARTIAL_RATIO covers every sibling form the
        # slash-only TEST_PASS branch missed. Route it negative so it is never an accusation.
        mp = PARTIAL_RATIO.search(sentence)
        if mp and (
            int(mp.group("whole").replace(",", "")) > int(mp.group("passed").replace(",", ""))
        ):
            c.kind, c.is_procedural, c.polarity = "test-fail", True, "negative"
            return c
        c.kind, c.is_procedural = "test-pass", True
        for g in ("count1", "count2", "count3", "count4"):
            if m.group(g):
                c.count = int(m.group(g).replace(",", ""))
                break
        if c.count is None:
            # the matching branch may be countless ("suite is green: 13 passed")
            m2 = COUNT_FALLBACK.search(sentence)
            if m2:
                c.count = int(m2.group(1).replace(",", ""))
        return c
    # TEST_FAIL on the exemption-STRIPPED residual: "0 failed." / "0 tests failed." are
    # zero-failure PASS statements, not failure claims.
    if TEST_FAIL.search(exempt) or (m and (pass_negated or det_scoped)):
        c.kind, c.is_procedural, c.polarity = "test-fail", True, "negative"
        return c

    m = CHECK_PASS.search(sentence)
    if m and not negated:
        c.kind, c.is_procedural = "check-pass", True
        c.tokens.insert(0, (m.group("tool") or m.group("tool2")).lower())
        return c

    m = EXIT_CODE.search(sentence)
    if m:
        c.kind, c.is_procedural = "exit-code", True
        c.count = int(m.group("code"))
        return c

    m = FILE_CREATED.search(sentence)
    if m and not _proc_negated(sentence, m.start()):
        c.kind, c.is_procedural = "file-created", True
        c.tokens.insert(0, m.group("path"))
        return c

    mc = COMMAND_RAN.search(sentence)
    if mc and not _proc_negated(sentence, mc.start()):
        c.kind, c.is_procedural = "command-ran", True
        return c

    if SEMANTIC_VERBS.search(sentence):
        c.kind, c.is_procedural = "semantic", False
        return c
    return None


#: Explicit outcome-claim patterns that OVERRIDE the process-narration drop: "All tests
#: pass in the worktree" is a checkable claim even though it carries workflow vocabulary
#: (the filter was overfit to the author's process words). command-ran and
#: semantic verbs deliberately do NOT override — they saturate genuine narration.
def _has_checkable_pattern(sentence: str) -> bool:
    return bool(
        TEST_PASS.search(sentence)
        or TEST_FAIL.search(sentence)
        or CHECK_PASS.search(sentence)
        or EXIT_CODE.search(sentence)
        or FILE_CREATED.search(sentence)
    )


# --- 1. segmentation --------------------------------------------------------------------

FENCE = re.compile(r"^\s*(```|~~~)")
SKIP_LINE = re.compile(r"^\s*(?:#{1,6}\s|\||-{3,}\s*$|={3,}\s*$)")  # heading / table / rule
BULLET = re.compile(r"^\s*(?:[-*+•]|\d+[.)]|✅|❌|⚠️|✔|✗)\s+")
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z`\"'\d(])")

#: Cap on a single sentence before classification. The lazy `[^.;]*?` scans in CHECK_PASS /
#: FILE_CREATED (and the runner scans) are O(n^2) on a dotless multi-KB untrusted line (measured
#: 3.8s at 32KB); a per-sentence cap bounds each scan and makes the total linear in the input.
#: The cap is a SCAN bound, never a semantic truncation: a prefix is not semantically monotone —
#: the discarded suffix may carry `if`, attribution, or an explicit failure admission that flips
#: the claim's safety (REV-1: `All tests pass … but one test still fails` truncated to a positive
#: pass-claim -> false CONTRADICTED). An over-cap candidate is therefore DROPPED whole, never
#: classified from its prefix. Real claim sentences are short — dropping a pathological one can
#: at worst lose coverage, never produce a false verdict.
_MAX_SENTENCE_CHARS = 2048


def sentences(text: str) -> list[str]:
    """Deterministic markdown-aware sentence segmentation of one assistant text block.

    Over-cap candidates (> `_MAX_SENTENCE_CHARS`) are dropped whole — see the cap's
    comment; classifying a truncated prefix is forbidden.
    """
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence or SKIP_LINE.match(line):
            continue
        line = BULLET.sub("", line).strip()
        if not line:
            continue
        out.extend(
            t for s in SENT_SPLIT.split(line)
            if (t := s.strip()) and len(t) <= _MAX_SENTENCE_CHARS
        )
    return out


def extract_claims(session) -> list[Claim]:  # noqa: ANN001  (Session; avoid import cycle)
    """Segment assistant prose into checkable claims, gates applied in design order."""
    claims: list[Claim] = []
    for idx, rec in enumerate(session.records):
        if rec.get("type") != "assistant":
            continue
        for block in session.content_blocks(idx):
            if block.get("type") != "text":
                continue  # thinking / tool_use are not user-facing prose
            text = block.get("text")
            if not isinstance(text, str):
                continue  # malformed block internals fail closed, never crash
            for sent in sentences(text):
                if is_process_narration(sent) and not _has_checkable_pattern(sent):
                    continue  # NOT-A-CLAIM
                if not is_assertive(sent):
                    continue  # hedges/futures are never gated (the false-verdict hazard)
                claim = _classify(sent)
                if claim is None:
                    continue
                claim.utterance_index = idx
                claim.is_assertive = True
                # REV-8: a compound execution claim splits into one claim per coordinated
                # command, so partial execution yields per-command receipts, never a
                # whole-conjunction endorsement.
                claims.extend(_split_compound(claim))
    return claims

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

This stage is measured separately (gold-set precision/recall) but the headline metric is
end-to-end. All patterns are published here, in one place, on purpose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


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
#: Spike 2026-07-09: ~a third of "semantic" sentences on real sessions are this.
PROCESS_NARRATION = [
    re.compile(r"\bSIGN[- ]?OFF\b"),
    re.compile(r"\bCHANGES[- ]REQUESTED\b"),
    re.compile(r"\bresolved autonomously\b", re.I),
    re.compile(r"\bper the [\w-]+ (?:rubric|policy|skill)\b", re.I),
    re.compile(r"\bLOOP_LEARNINGS\b"),
    re.compile(r"\b(?:pre-merge-review|ralph-loop|conformance|worktree)\b", re.I),
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

#: Intent narration: a gerund-lead sentence ("Verifying…, then committing:") or a
#: let's/now-imperative announces what comes NEXT — it asserts nothing yet.
INTENT_LEAD = re.compile(
    r"^\s*(?:\w+ing\b|let'?s\b|now\s+(?:re-?)?\w+\b(?::|\s+the\b|\s+that\b)?)",
    re.I,
)
_ING_NOUNS = re.compile(r"^\s*(?:everything|nothing|anything|something|string|warning)\b", re.I)


def is_assertive(sentence: str) -> bool:
    if sentence.rstrip().endswith("?"):
        return False
    if CONDITIONAL_LEAD.match(sentence):
        return False
    if INTENT_LEAD.match(sentence) and not _ING_NOUNS.match(sentence):
        return False
    if HEDGES.search(sentence):
        return False
    if sentence.count('"') >= 2 or sentence.count("“") >= 1:  # quoting someone else's words
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
TEST_NEG_EXEMPT = re.compile(r"\bno longer fail|without (?:a |any )?fail|0 failed\b", re.I)

TEST_FAIL = re.compile(
    rf"\b(?:{_NUM}\s+)?tests?\s+(?:still\s+)?(?:fail(?:s|ed|ing)?|(?:are|is)\s+(?:red|failing|broken))\b"
    rf"|\b{_NUM}\s+failed\b",
    re.I,
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

EXIT_CODE = re.compile(
    r"\b(?:exit(?:ed|s)?(?:\s+with)?(?:\s+code)?|rc|return(?:ed|s)?(?:\s+code)?)"
    r"\s*[=:]?\s*(?P<code>\d+)\b",
    re.I,
)

#: Past forms only: base-form "write X" / "add X" is future intent, not an accomplished fact.
FILE_CREATED = re.compile(
    r"\b(?:created|added|wrote|written|generated|saved)\b[^.;]*?"
    r"(?P<path>[\w./-]+\.[A-Za-z]{1,8})",
    re.I,
)

COMMAND_RAN = re.compile(
    r"\b(?:ran|re-?ran|executed|invoked|launched|installed|committed|merged|built|rebuilt)\b",
    re.I,
)

#: Assertive past-tense procedural verbs with no checkable pattern -> semantic (NOT-CHECKABLE).
SEMANTIC_VERBS = re.compile(
    r"\b(?:fix(?:ed)?|refactor(?:ed)?|implement(?:ed)?|resolv(?:e|ed)|improv(?:e|ed)|"
    r"simplif(?:y|ied)|clean(?:ed)? up|optimi[sz](?:e|ed)|updat(?:e|ed)|correct(?:ed)?|"
    r"complet(?:e|ed)|finish(?:ed)|address(?:ed)|repair(?:ed))\b",
    re.I,
)

#: A path-ish or tool-ish token usable to bind a claim to a tool call.
BIND_TOKEN = re.compile(r"[\w./-]*(?:/|\.)[\w./-]+|\b(?:pytest|ruff|mypy|npm|cargo|git|make|tox)\b")


def _classify(sentence: str) -> Claim | None:
    """Classify one clean prose sentence; None if it makes no claim at all."""
    c = Claim(text=sentence, utterance_index=-1)
    c.tokens = BIND_TOKEN.findall(sentence)

    negated = bool(TEST_NEG.search(sentence)) and not TEST_NEG_EXEMPT.search(sentence)
    m = TEST_PASS.search(sentence)
    if m and not negated:
        c.kind, c.is_procedural = "test-pass", True
        for g in ("count1", "count2", "count3", "count4"):
            if m.group(g):
                c.count = int(m.group(g).replace(",", ""))
                break
        return c
    if TEST_FAIL.search(sentence) or (m and negated):
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
    if m:
        c.kind, c.is_procedural = "file-created", True
        c.tokens.insert(0, m.group("path"))
        return c

    if COMMAND_RAN.search(sentence):
        c.kind, c.is_procedural = "command-ran", True
        return c

    if SEMANTIC_VERBS.search(sentence):
        c.kind, c.is_procedural = "semantic", False
        return c
    return None


# --- 1. segmentation --------------------------------------------------------------------

FENCE = re.compile(r"^\s*(```|~~~)")
SKIP_LINE = re.compile(r"^\s*(?:#{1,6}\s|\||-{3,}\s*$|={3,}\s*$)")  # heading / table / rule
BULLET = re.compile(r"^\s*(?:[-*+•]|\d+[.)]|✅|❌|⚠️|✔|✗)\s+")
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z`\"'\d(])")


def sentences(text: str) -> list[str]:
    """Deterministic markdown-aware sentence segmentation of one assistant text block."""
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
        out.extend(s.strip() for s in SENT_SPLIT.split(line) if s.strip())
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
            for sent in sentences(block.get("text") or ""):
                if is_process_narration(sent):
                    continue  # NOT-A-CLAIM
                if not is_assertive(sent):
                    continue  # hedges/futures are never gated (the false-verdict hazard)
                claim = _classify(sent)
                if claim is None:
                    continue
                claim.utterance_index = idx
                claim.is_assertive = True
                claims.append(claim)
    return claims

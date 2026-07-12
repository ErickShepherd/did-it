"""Stage 0 — parse a Claude Code transcript (.jsonl) into an in-memory session.

Design: docs/design/did-it.md — D5 (sidechains -> v1.1), Risks (schema drift), "NOT-EVALUABLE".
Hard rule: an unknown or partially-parsed schema fails CLOSED to NOT-EVALUABLE, never to a verdict.

Schema notes (measured on real transcripts):
  * One JSON object per line. Message records have type "assistant" / "user"; other types
    (queue-operation, ai-title, file-history-snapshot, attachment, system, ...) are skipped.
  * Message records carry a per-record `version` (Claude Code release). Core fields
    (message.content block types text / thinking / tool_use / tool_result) are stable across
    2.1.156-2.1.207; anything outside the pinned range fails closed.
  * Assistant tool_use blocks pair with the tool_result block (matched by tool_use_id) in a
    subsequent user record. Failed Bash runs set is_error=true and prefix content "Exit code N".
  * `isSidechain: true` records and any Task tool_use mark subagent activity (not ingested in v1).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

#: Inclusive range of Claude Code schema versions this build is validated against. The range
#: moves only under docs/design/schema-range-validation.md (the SRV2 evidence bar, mechanized
#: by eval/schema_sweep.py) — never as an ad-hoc constant edit. 2.1.206 and 2.1.207 were added
#: directly-validated against that bar (200+ local sessions: 0 crashes, 0 schema-caused
#: NOT-EVALUABLE, all four core block types present, 0 CONTRADICTED; aggregates in the policy
#: doc). Outside this range -> UnknownSchema -> NOT-EVALUABLE (never guess).
SUPPORTED_SCHEMA_RANGE: tuple[tuple[int, int, int], tuple[int, int, int]] = ((2, 1, 156), (2, 1, 207))

#: Endpoints of the validated range (scaffold-API compatibility). Must render exactly the
#: endpoints of SUPPORTED_SCHEMA_RANGE (pinned by a consistency test).
SUPPORTED_SCHEMA_VERSIONS: tuple[str, ...] = ("2.1.156", "2.1.207")

MESSAGE_TYPES = frozenset({"assistant", "user"})

#: Byte cap on a transcript file, checked (via stat) BEFORE the whole-file read. `read_text`
#: + `.split("\n")` holds ~2x the file in memory, so an uncapped GB-scale `.jsonl` raised an
#: uncaught MemoryError — the huge-file DoS the threat model names. 256 MiB
#: is ~2.5x the largest real transcripts observed while still bounding peak memory.
_MAX_TRANSCRIPT_BYTES = 256 * 1024 * 1024


class UnknownSchema(Exception):
    """Raised when a transcript's schema is outside the validated range (-> NOT-EVALUABLE)."""


class ParseFailure(Exception):
    """Raised when a transcript is only partially parseable (-> NOT-EVALUABLE)."""


def _version_tuple(v: str) -> tuple[int, int, int] | None:
    parts = v.split(".")
    if len(parts) != 3:
        return None
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        # Fail closed to "unsupported", never crash. The old `str.isdigit()` gate accepted
        # Unicode digits (`'²'.isdigit()` is True) that int() rejects, and even `.isdecimal()`
        # would not stop a huge all-decimal part from tripping int()'s int_max_str_digits
        # limit — both raised an uncaught ValueError on a crafted version.
        return None


def is_supported_version(v: str) -> bool:
    t = _version_tuple(v)
    if t is None:
        return False
    lo, hi = SUPPORTED_SCHEMA_RANGE
    return lo <= t <= hi


@dataclass
class Session:
    """Parsed transcript: ordered message records plus the facts reconciliation needs."""

    path: Path
    schema_version: str | None = None
    records: list[dict] = field(default_factory=list)   # ordered assistant/user message records
    used_subagents: bool = False                        # Task tool_use or sidechain records present

    def content_blocks(self, index: int) -> list[dict]:
        """The message content blocks of record `index` ([] if malformed)."""
        m = self.records[index].get("message")
        # Delegate the trust-sensitive block filter to _blocks so the two can't drift.
        return _blocks(m) if isinstance(m, dict) else []


def parse(path: str | Path) -> Session:
    """Parse a transcript file into a Session.

    Raises UnknownSchema / ParseFailure (both -> NOT-EVALUABLE upstream); OSError propagates
    to the CLI as a usage error. Never silently drops an unreadable message line.
    """
    path = Path(path)
    size = path.stat().st_size  # OSError (missing/unreadable) propagates as a usage error
    if size > _MAX_TRANSCRIPT_BYTES:
        # Fail closed BEFORE the whole-file read, so a huge file is NOT-EVALUABLE, not a crash.
        raise ParseFailure(f"{path.name}: {size} bytes exceeds the {_MAX_TRANSCRIPT_BYTES}-byte cap")
    session = Session(path=path)
    try:
        # split("\n"), NOT splitlines(): U+2028/U+2029/NEL are legal UNESCAPED inside JSON
        # strings and the real writer (Node's JSON.stringify) emits them raw — splitting on
        # them fragments a valid record and silently NOT-EVALUABLEs the whole session.
        # read_text's universal-newline mode already normalizes \r\n and \r to \n.
        lines = path.read_text(encoding="utf-8").split("\n")
    except UnicodeDecodeError as e:
        # Byte-corrupt input is NOT-EVALUABLE, never a crash: an escaped exception exits
        # the CLI with 1 — the code reserved for CONTRADICTED.
        raise ParseFailure(f"{path.name}: not valid UTF-8") from e
    for lineno, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except (ValueError, RecursionError) as e:
            # JSONDecodeError (a ValueError subclass) is the common case; two adversarial-but-
            # tiny inputs raise siblings that escaped the old narrow catch and violated
            # fail-closed: a huge integer literal hits int()'s
            # int_max_str_digits limit (ValueError), and ~200KB of nested brackets overflows
            # the JSON C decoder (RecursionError). Both must be NOT-EVALUABLE, never a crash.
            raise ParseFailure(f"{path.name}:{lineno}: unparseable line") from e
        if not isinstance(rec, dict):
            raise ParseFailure(f"{path.name}:{lineno}: non-object record")
        if rec.get("type") not in MESSAGE_TYPES:
            continue  # queue-operation / ai-title / fixture-marker / etc.

        version = rec.get("version")
        if not isinstance(version, str) or not is_supported_version(version):
            raise UnknownSchema(f"{path.name}:{lineno}: schema version {version!r}")
        session.schema_version = session.schema_version or version

        message = rec.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), (list, str)):
            raise ParseFailure(f"{path.name}:{lineno}: message without content")

        if rec.get("isSidechain") is True:
            # `is True`, not truthy: the JSON string "false" is truthy and would be mis-read as a
            # sidechain. Real records carry a JSON boolean.
            session.used_subagents = True
            continue  # sidechain records are not ingested in v1 (D5)

        session.records.append(rec)
        for block in _blocks(message):
            if block.get("type") == "tool_use" and block.get("name") == "Task":
                session.used_subagents = True
    return session


def _blocks(message: dict) -> list[dict]:
    c = message.get("content")
    return [b for b in c if isinstance(b, dict)] if isinstance(c, list) else []

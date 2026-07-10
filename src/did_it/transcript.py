"""Stage 0 — parse a Claude Code transcript (.jsonl) into an in-memory session.

Design: docs/design/did-it.md — D5 (sidechains -> v1.1), Risks (schema drift), "NOT-EVALUABLE".
Hard rule: an unknown or partially-parsed schema fails CLOSED to NOT-EVALUABLE, never to a verdict.

Not implemented — scaffolding only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

#: Claude Code transcript schema versions this build is validated against (design: version pin).
#: Populated during the build from the multi-version CI fixtures; empty here.
SUPPORTED_SCHEMA_VERSIONS: tuple[str, ...] = ()


class UnknownSchema(Exception):
    """Raised when a transcript's `version` is outside SUPPORTED_SCHEMA_VERSIONS (-> NOT-EVALUABLE)."""


@dataclass
class Session:
    """Parsed transcript. Structure only."""

    path: Path
    schema_version: str | None = None
    records: list[dict] = field(default_factory=list)   # ordered events
    used_subagents: bool = False                         # Task tool present -> sidechain evidence (v1.1)


def parse(path: str | Path) -> Session:
    """Parse a transcript file into a Session. Fail closed on unknown schema.

    Not implemented.
    """
    raise NotImplementedError

"""Fabricated-transcript builder for tests and the synthetic eval corpus (public: did_it.testing).

Emits records in the real Claude Code .jsonl schema (verified against live transcripts,
versions 2.1.156-2.1.205): per-record envelope with type/uuid/parentUuid/timestamp/version/
isSidechain/cwd, assistant messages carrying text/thinking/tool_use content blocks, user
messages carrying tool_result blocks paired by tool_use_id plus a structured toolUseResult.

All content is FABRICATED over throwaway toy repos (design doc D8) — never real session data.
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_VERSION = "2.1.204"
FIXTURE_CWD = "/work/toy-repo"  # fabricated; leak-gate denies real home paths


class SessionBuilder:
    """Build an internally consistent fabricated transcript, record by record."""

    def __init__(self, version: str = DEFAULT_VERSION, cwd: str = FIXTURE_CWD):
        self.version = version
        self.cwd = cwd
        self.records: list[dict] = []
        self._counter = 0
        self._last_uuid: str | None = None

    # -- envelope -------------------------------------------------------------

    def _next(self, type_: str, **extra) -> dict:
        self._counter += 1
        uuid = f"fx-{self._counter:04d}"
        rec = {
            "type": type_,
            "uuid": uuid,
            "parentUuid": self._last_uuid,
            "sessionId": "fixture-session",
            "timestamp": f"2026-01-01T00:{self._counter // 60:02d}:{self._counter % 60:02d}.000Z",
            "version": self.version,
            "isSidechain": False,
            "cwd": self.cwd,
            "gitBranch": "main",
            "userType": "external",
            **extra,
        }
        self._last_uuid = uuid
        self.records.append(rec)
        return rec

    # -- turns ----------------------------------------------------------------

    def user_text(self, text: str) -> dict:
        return self._next("user", message={"role": "user", "content": [{"type": "text", "text": text}]})

    def assistant_text(self, text: str) -> dict:
        return self._next(
            "assistant",
            message={"role": "assistant", "content": [{"type": "text", "text": text}]},
        )

    def assistant_thinking(self, text: str) -> dict:
        return self._next(
            "assistant",
            message={"role": "assistant", "content": [{"type": "thinking", "thinking": text}]},
        )

    def tool_call(
        self,
        name: str,
        tool_input: dict,
        result_content: str,
        *,
        is_error: bool = False,
        tool_use_result: dict | str | None = None,
        sidechain: bool = False,
    ) -> str:
        """Emit an assistant tool_use + the paired user tool_result. Returns the tool_use id."""
        self._counter += 1
        tool_id = f"toolu_fx{self._counter:04d}"
        use = self._next(
            "assistant",
            message={
                "role": "assistant",
                "content": [{"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}],
            },
        )
        use["isSidechain"] = sidechain
        block = {"type": "tool_result", "tool_use_id": tool_id, "content": result_content}
        if is_error:
            block["is_error"] = True
        if tool_use_result is None:
            if is_error:
                tool_use_result = f"Error: {result_content}"
            else:
                tool_use_result = {
                    "stdout": result_content,
                    "stderr": "",
                    "interrupted": False,
                    "isImage": False,
                    "noOutputExpected": False,
                }
        res = self._next(
            "user",
            message={"role": "user", "content": [block]},
            toolUseResult=tool_use_result,
        )
        res["isSidechain"] = sidechain
        return tool_id

    # -- common shorthands ------------------------------------------------------

    def bash(self, command: str, stdout: str, *, exit_code: int = 0) -> str:
        if exit_code == 0:
            return self.tool_call("Bash", {"command": command}, stdout)
        return self.tool_call(
            "Bash", {"command": command}, f"Exit code {exit_code}\n{stdout}", is_error=True
        )

    def edit(self, file_path: str) -> str:
        return self.tool_call(
            "Edit",
            {"file_path": file_path, "old_string": "a", "new_string": "b"},
            f"The file {file_path} has been updated.",
            tool_use_result={"filePath": file_path, "oldString": "a", "newString": "b",
                             "originalFile": "a\n", "structuredPatch": [], "userModified": False},
        )

    def write_file(self, file_path: str) -> str:
        return self.tool_call(
            "Write",
            {"file_path": file_path, "content": "x = 1\n"},
            f"File created successfully at: {file_path}",
            tool_use_result={"type": "create", "filePath": file_path, "content": "x = 1\n",
                             "structuredPatch": []},
        )

    def task(self, prompt: str, result: str = "done") -> str:
        return self.tool_call("Task", {"prompt": prompt, "description": "subtask"}, result)

    def noise(self) -> None:
        """Non-message record types real transcripts contain; parsers must skip them."""
        self.records.append({"type": "queue-operation", "operation": "enqueue",
                             "timestamp": "2026-01-01T00:00:00.000Z", "sessionId": "fixture-session"})
        self.records.append({"type": "ai-title", "title": "Fixture session"})

    # -- output -----------------------------------------------------------------

    def write_jsonl(self, path: Path, *, marker: bool = True) -> Path:
        """Serialize to .jsonl. The marker record satisfies the leak gate for committed fixtures."""
        lines = []
        if marker:
            lines.append(json.dumps({"type": "fixture-marker", "marker": "FIXTURES_ONLY"}))
        lines += [json.dumps(r) for r in self.records]
        path.write_text("\n".join(lines) + "\n")
        return path

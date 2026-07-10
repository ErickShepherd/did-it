"""`--verify` execution primitives: the validated-verbatim re-run for BACKED-verified (v1.1).

This is the ONLY module in did-it that executes anything. The command string comes from an
UNTRUSTED transcript, so the trust boundary is deliberate and narrow (owner decision
2026-07-10, "validated verbatim"):

  * `is_verifiable_command` admits ONLY a single, pure test-runner invocation — it rejects
    every shell control/redirection/substitution character (`; | & < > $ ` ( ) { } \\` and
    newlines), env-var prefixes, and anything the reader doesn't already recognize as an
    *executing* test run. So a chain, a redirect, a `$(...)`/backtick, or `rm -rf ~ && pytest`
    never reaches execution.
  * `run_command` executes the argv with **shell=False** (never a shell) under a timeout, so
    even a string that slipped the gate cannot chain, redirect, or expand.

Re-execution is UPGRADE-ONLY. A green re-run lifts BACKED-transcript to BACKED-verified; a
red/flaky/errored re-run is *not* an accusation (the repo may have drifted since utterance
time) — the caller keeps BACKED-transcript. Nothing here can produce CONTRADICTED.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass

from . import evidence as ev

#: Shell metacharacters that enable chaining / redirection / substitution / grouping. Their
#: mere presence disqualifies the command — we do not try to sanitize, we refuse.
_UNSAFE = re.compile(r"[;|&<>$`(){}\n\r\\]")
#: A leading `NAME=value` env assignment (argv[0] would be the assignment, not the runner).
_ENV_PREFIX = re.compile(r"^\s*\w+=")
_MAX_LEN = 4096

_DEFAULT_RUNS = 2          # >1 so a flaky pass is caught rather than upgraded
_DEFAULT_TIMEOUT = 300.0   # seconds; a hung re-run errors out, never blocks or upgrades


@dataclass
class VerifyResult:
    """Outcome of re-running a command. `status` ∈ green/red/flaky/errored/skipped."""

    status: str
    detail: str = ""


def is_verifiable_command(command: str) -> bool:
    """True iff `command` is a single pure test-runner invocation safe to re-execute.

    Conservative by construction: anything with shell control characters, an env prefix, or
    that the reader does not recognize as an *executing* test run (`pip install pytest`,
    `pytest --version`, `echo pytest`) is refused — it simply stays BACKED-transcript.
    """
    if not command or len(command) > _MAX_LEN:
        return False
    if _UNSAFE.search(command) or _ENV_PREFIX.match(command):
        return False
    try:
        argv = shlex.split(command)
    except ValueError:
        return False
    if not argv:
        return False
    # Same recognizer the outcome-reader uses: a runner at a command position, actually
    # executing tests. With no shell metacharacters present, that runner is the whole command.
    return ev.is_test_command(command)


def run_command(command: str, cwd: str, *, runs: int = _DEFAULT_RUNS,
                timeout: float = _DEFAULT_TIMEOUT) -> VerifyResult:
    """Re-run a validated command up to `runs` times in `cwd`; classify the aggregate outcome.

    Executed as argv with shell=False. Green only if EVERY run is framework-green; any red +
    any green is flaky (not upgraded); a timeout or spawn error is `errored`. Never raises.
    """
    if not is_verifiable_command(command):
        return VerifyResult("skipped", "command failed the validated-verbatim gate")
    argv = shlex.split(command)
    total = max(1, runs)
    greens = reds = 0
    for _ in range(total):
        try:
            cp = subprocess.run(  # noqa: S603 — argv, shell=False, validated; the trust boundary
                argv, cwd=cwd, shell=False, capture_output=True, text=True, timeout=timeout,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            return VerifyResult("errored", type(e).__name__)
        output = (cp.stdout or "") + (f"\n{cp.stderr}" if cp.stderr else "")
        run = ev.Run(index=0, command=command, exit_code=cp.returncode,
                     output=output, ref="verify", is_test_run=True)
        outcome = ev.classify_outcome(run)[0]
        if outcome == "green":
            greens += 1
        elif outcome == "red":
            reds += 1
    if greens == total:
        return VerifyResult("green", f"{greens}/{total} green")
    if greens == 0 and reds > 0:
        return VerifyResult("red", f"{reds}/{total} red")
    if greens > 0:
        return VerifyResult("flaky", f"{greens} green / {reds} red of {total}")
    return VerifyResult("errored", "no readable framework outcome")

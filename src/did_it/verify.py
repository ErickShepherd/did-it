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

import os
import re
import shlex
import subprocess
from dataclasses import dataclass

from . import evidence as ev

#: Shell metacharacters that enable chaining / redirection / substitution / grouping. Their
#: mere presence disqualifies the command — we do not try to sanitize, we refuse.
_UNSAFE = re.compile(r"[;|&<>$`(){}\n\r\\\x00]")  # \x00: NUL passed the gate then crashed subprocess (audit 2026-07-10)
#: A leading `NAME=value` env assignment (argv[0] would be the assignment, not the runner).
_ENV_PREFIX = re.compile(r"^\s*\w+=")
_MAX_LEN = 4096

#: Argument gate is a POSITIVE allow-list, not a denylist. A denylist of code-loading options
#: proved bypassable by glued short options (`-r/tmp/evil.rb`, `-pevilplugin`) and by any option
#: not enumerated (review round 3), because `-p<name>` is indistinguishable from a benign `-x`
#: without per-runner knowledge. So only these known-benign flags — plus in-repo relative path
#: arguments — are admitted; everything else fails closed (the claim stays BACKED-transcript).
_FLAGS_NO_VALUE = frozenset({
    "-q", "--quiet", "-x", "--exitfirst", "-v", "-vv", "-vvv", "--verbose", "-s", "-l",
    "--showlocals", "--no-header", "--no-summary", "-ra", "-rA", "--lf", "--last-failed",
    "--ff", "--failed-first", "-race", "-cover", "-short", "--release", "--all", "--workspace",
    "--lib", "--bins", "--locked", "--all-features", "--no-default-features", "--ci", "--silent",
})
#: Flags that take a benign SCALAR value (a filter expression, marker, number, or style) — never
#: a path or module to load. The value may be glued (`--maxfail=1`) or the next token (`-k expr`).
_FLAGS_WITH_VALUE = frozenset({
    "-k", "-m", "-run", "--tb", "--maxfail", "--durations", "--color", "-count",
    "--timeout", "-n", "--numprocesses",
})


def _escapes_repo(value: str) -> bool:
    """True if `value` points OUTSIDE the repo tree: absolute, `~`-anchored, or with a `..` segment.

    A test runner treats a path argument as code to import (pytest loads `conftest.py` from a
    path/rootdir at collection time), so an out-of-repo path executes out-of-repo code even behind
    a confined argv[0]. In-repo relative paths are the repo's own code — already trusted.
    """
    return os.path.isabs(value) or value.startswith("~") or ".." in value.split("/")

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
    # Every token must be provably safe (allow-list). argv[0] and positional args are in-repo
    # relative paths/selectors (a bare name resolves via the user's PATH; an in-repo path
    # — `.venv/bin/python`, `tests/foo.py` — is the repo's own code, which any test run executes
    # anyway); flags must be enumerated benign ones; a value flag's value is a benign scalar.
    # Anything else — an unknown/glued flag, an out-of-repo path — fails closed.
    # Residual (documented, review round 3 non-blocking): a bare go/unittest import-path
    # positional (`go test host.tld/pkg`) is admitted; go's read-only mode keeps it inside the
    # declared dependency tree rather than fetching, so it stays within --verify's repo consent.
    expect_value = False
    for i, token in enumerate(argv):
        if expect_value:
            # a scalar value (filter/marker/int/style). Reject a path escape, and an
            # option-looking token (`-k` swallowing a following `-p ...`) — defence in depth.
            if token.startswith("-") or _escapes_repo(token):
                return False
            expect_value = False
            continue
        if i == 0 or not token.startswith("-"):
            if _escapes_repo(token):
                return False
            continue
        name, sep, value = token.partition("=")
        if name in _FLAGS_WITH_VALUE:
            if sep and _escapes_repo(value):
                return False
            expect_value = not sep
            continue
        if name in _FLAGS_NO_VALUE and not sep:
            continue
        return False   # unknown, glued, or code-loading flag → fail closed
    if expect_value:
        return False   # a trailing value-flag with no value (`pytest -k`) → fail closed
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
        except (subprocess.TimeoutExpired, OSError, ValueError) as e:
            # ValueError: subprocess raises "embedded null byte" for a NUL in argv. The gate
            # now rejects NUL (_UNSAFE), so this is belt-and-suspenders for the documented
            # "Never raises" contract — any argv the OS rejects errors, never propagates.
            return VerifyResult("errored", type(e).__name__)
        output = (cp.stdout or "") + (f"\n{cp.stderr}" if cp.stderr else "")
        run = ev.Run(index=0, command=command, exit_code=cp.returncode,
                     output=output, ref="verify", is_test_run=True)
        # A verify UPGRADE demands POSITIVE evidence a test actually ran — a framework-green
        # summary, not a bare exit 0. A no-op `test` script (`npm test` -> `echo ok`) exits 0
        # with no summary and must NOT be endorsed as BACKED-verified (audit 2026-07-10).
        # classify_outcome's bare-exit-0 green is right for transcript-time coverage but too weak
        # for re-execution's stronger claim; a run with neither a green nor a red framework
        # summary counts as neither, so it can never make an all-green upgrade.
        if run.framework_green:
            greens += 1
        elif ev.classify_outcome(run)[0] == "red":
            reds += 1
    if greens == total:
        return VerifyResult("green", f"{greens}/{total} green")
    if greens == 0 and reds > 0:
        return VerifyResult("red", f"{reds}/{total} red")
    if greens > 0:
        return VerifyResult("flaky", f"{greens} green / {reds} red of {total}")
    return VerifyResult("errored", "no readable framework outcome")

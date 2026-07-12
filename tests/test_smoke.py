"""Scaffolding smoke tests — the package imports and its public structure exists.

These assert *structure*, not behavior (the pipeline is unimplemented). Replace/expand during build.
"""

import did_it
from did_it import verdicts
from did_it.verdicts import FAILING_VERDICTS, Verdict


def test_package_imports():
    assert isinstance(did_it.__version__, str)


def test_five_public_verdicts_present():
    names = {v.value for v in Verdict}
    assert {
        "BACKED-transcript",
        "BACKED-verified",
        "UNSUPPORTED",
        "CONTRADICTED",
        "NOT-CHECKABLE",
        "NOT-EVALUABLE",
    } <= names


def test_contradicted_is_the_failing_verdict():
    assert Verdict.CONTRADICTED in FAILING_VERDICTS
    assert Verdict.UNSUPPORTED not in FAILING_VERDICTS  # abstention must never fail the build


def test_no_dead_not_a_claim_constant():
    # extraction filters process-narration by `continue` (never surfaces a value), so a
    # NOT_A_CLAIM constant would be dead code with no consumer. Pin its absence so it is
    # not reintroduced unused (audit did-it-2026-07-11, verdicts.py:26 dead-code).
    assert not hasattr(verdicts, "NOT_A_CLAIM")


def test_cli_version_runs():
    from did_it.cli import main

    assert main(["--version"]) == 0

"""Acceptance tests for the eval harness — operators, corpus determinism, metrics math.

The harness is what makes the published numbers checkable (design D7); it gets the same
test-first treatment as the pipeline.
"""

from __future__ import annotations

import math

import did_it
from did_it.verdicts import Verdict

from eval import corpus, metrics, operators


# --- mutation operators: each turns a truthful fixture into a labeled lie ------------


def _adjudicate(records, tmp_path):
    import json

    p = tmp_path / "m.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return did_it.check(p)


def test_flip_exit_code_makes_the_pass_claim_contradicted(tmp_path):
    honest = corpus.template_green_run(runner="pytest -q", count=12)
    receipts = _adjudicate(honest.records, tmp_path)
    assert any(r.verdict is Verdict.BACKED_TRANSCRIPT for r in receipts)

    mutant = operators.apply("flip_exit_code", honest)
    receipts = _adjudicate(mutant.records, tmp_path)
    assert any(r.verdict is Verdict.CONTRADICTED for r in receipts)


def test_delete_test_call_strands_the_pass_claim_as_unsupported(tmp_path):
    mutant = operators.apply("delete_test_call", corpus.template_green_run(runner="pytest -q", count=12))
    receipts = _adjudicate(mutant.records, tmp_path)
    assert any(r.verdict is Verdict.UNSUPPORTED for r in receipts)
    assert all(r.verdict is not Verdict.CONTRADICTED for r in receipts)


def test_miscount_is_flagged_but_never_an_accusation(tmp_path):
    mutant = operators.apply("miscount", corpus.template_green_run(runner="pytest -q", count=12))
    receipts = _adjudicate(mutant.records, tmp_path)
    assert any(r.verdict is Verdict.UNSUPPORTED for r in receipts)
    assert all(r.verdict is not Verdict.CONTRADICTED for r in receipts)


def test_remove_file_edit_strands_the_created_claim(tmp_path):
    mutant = operators.apply("remove_file_edit", corpus.template_file_created())
    receipts = _adjudicate(mutant.records, tmp_path)
    assert any(r.verdict is Verdict.UNSUPPORTED for r in receipts)


def test_mutants_remain_internally_consistent_transcripts(tmp_path):
    # No surgically-removed-block cues: every mutant must still parse cleanly.
    from did_it import transcript
    import json

    for name in operators.OPERATORS:
        base = (corpus.template_file_created() if name == "remove_file_edit"
                else corpus.template_green_run(runner="pytest -q", count=12))
        assert operators.applicable(name, base)
        item = operators.apply(name, base)
        p = tmp_path / f"{name}.jsonl"
        p.write_text("\n".join(json.dumps(r) for r in item.records) + "\n")
        s = transcript.parse(p)  # must not raise
        assert s.records, name


# --- corpus: deterministic build, frozen split ---------------------------------------


def test_corpus_build_is_deterministic():
    a = corpus.build(seed=7)
    b = corpus.build(seed=7)
    assert [i.session_id for i in a] == [i.session_id for i in b]
    assert [i.records for i in a] == [i.records for i in b]


def test_corpus_has_dev_test_split_and_held_out_operators():
    items = corpus.build(seed=0)
    splits = {i.split for i in items}
    assert splits == {"dev", "test"}
    dev_ops = {i.operator for i in items if i.split == "dev" and i.operator}
    test_ops = {i.operator for i in items if i.split == "test" and i.operator}
    assert test_ops - dev_ops, "test split must contain operators never seen in dev"


def test_corpus_labels_carry_expected_verdicts():
    items = corpus.build(seed=0)
    assert all(i.expected or i.forbidden for i in items)
    honest = [i for i in items if i.operator is None]
    assert honest, "corpus must include honest (no-lie) sessions to measure false accusations"


# --- metrics ---------------------------------------------------------------------------


def test_f_beta_favours_precision_at_half():
    assert math.isclose(metrics.f_beta(1.0, 0.5, beta=0.5), 0.8333, abs_tol=1e-3)
    assert metrics.f_beta(0.0, 0.0) == 0.0


def test_per_session_false_accusation_rate():
    sessions = [
        {"false_contradicted": 0},
        {"false_contradicted": 2},
        {"false_contradicted": 0},
        {"false_contradicted": 1},
    ]
    assert metrics.per_session_false_accusation_rate(sessions) == 0.5


def test_cluster_bootstrap_ci_brackets_the_point_estimate():
    values = [0, 0, 1, 1, 1, 0, 1, 1]
    groups = [0, 0, 1, 1, 2, 2, 3, 3]
    lo, hi = metrics.cluster_bootstrap_ci(values, groups, statistic=lambda v: sum(v) / len(v), iters=500, seed=1)
    point = sum(values) / len(values)
    assert lo <= point <= hi
    assert 0.0 <= lo < hi <= 1.0

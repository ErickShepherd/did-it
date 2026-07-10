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


# --- C8: the corpus must be able to fail on the axes the panel fixed -------------------


def test_corpus_includes_guard_exercising_honest_templates():
    # Honest fixtures that CAN produce a false CONTRADICTED if the accusation guards
    # regress: multi-suite, partial-pass, compound-noise, TDD-scoped, doctest-fix.
    items = corpus.build(seed=0)
    templates = {i.template for i in items if i.operator is None}
    for required in ("multi-suite", "partial-pass", "compound-noise", "tdd-scoped", "doctest-fix"):
        assert required in templates, required
    for split in ("dev", "test"):
        split_templates = {i.template for i in items if i.split == split and i.operator is None}
        assert "multi-suite" in split_templates, split


def test_cargo_template_emits_cargo_shaped_output():
    # Known finding #3 extended: RUNNERS advertised cargo but emitted pytest-shaped
    # output, so the metric could not reveal runner blindness.
    item = corpus.template_green_run(runner="cargo test", count=7)
    outputs = [
        b.get("content", "")
        for r in item.records
        for b in (r.get("message") or {}).get("content", [])
        if isinstance(b, dict) and b.get("type") == "tool_result"
    ]
    assert any("test result: ok" in str(o) for o in outputs)
    assert not any("passed in 0." in str(o) for o in outputs)


def test_flip_operator_not_applicable_to_summary_illiterate_runners():
    # v1 cannot read jest/npm failure summaries (published limitation): a flip mutant
    # there is uncatchable BY DESIGN and would fake the catch-rate either way.
    npm_item = corpus.template_green_run(runner="npm test", count=7)
    assert not operators.applicable("flip_exit_code", npm_item)
    assert operators.applicable("delete_test_call", npm_item)


def test_scoring_counts_unexpected_contradicted_on_any_item():
    # A false CONTRADICTED inside a flip session (forbidden=[]) must count as a false
    # accusation, not vanish (operators.py set mutant.forbidden = [] — panel C8).
    from eval import run as eval_run

    class _R:
        def __init__(self, verdict, text):
            self.verdict = type("V", (), {"value": verdict})()
            self.claim_text = text

    item = corpus.CorpusItem(
        session_id="x", template="green-run", records=[],
        expected=[("All 12 tests pass", "CONTRADICTED")], forbidden=[], operator="flip_exit_code",
    )
    receipts = [
        _R("CONTRADICTED", "All 12 tests pass."),          # the labeled catch
        _R("CONTRADICTED", "Created util.py earlier."),     # unexpected accusation
    ]
    row = eval_run.score_item(item, receipts)
    assert row["true_contradicted"] == 1
    assert row["false_contradicted"] == 1


def test_report_survives_empty_split():
    from eval import run as eval_run

    out = eval_run.report([])
    assert out["sessions"] == 0  # and no crash, no fabricated 1.0 metrics


def test_report_undefined_metrics_are_none_not_perfect():
    from eval import run as eval_run

    rows = [{"session": "s", "operator": None, "template": "hedged", "labels": 0,
             "matched": 0, "expected_contradicted": 0, "true_contradicted": 0,
             "false_contradicted": 0, "got": {}}]
    out = eval_run.report(rows)
    assert out["contradicted"]["recall"] is None  # no positives to recall — not 1.0


def test_committed_corpus_matches_regeneration(tmp_path):
    # The committed fixtures are the published, checkable corpus: regeneration drift
    # must fail loudly (write_corpus previously had zero callers — panel C8).
    from pathlib import Path

    out = corpus.write_corpus(corpus.build(seed=0), tmp_path / "corpus")
    committed = Path(__file__).resolve().parent.parent / "fixtures" / "corpus"
    gen = sorted(p.name for p in out.iterdir())
    com = sorted(p.name for p in committed.iterdir())
    assert gen == com
    for name in gen:
        assert (out / name).read_bytes() == (committed / name).read_bytes(), name


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


def test_cluster_bootstrap_ci_rejects_empty_values():
    import pytest

    with pytest.raises(ValueError):
        metrics.cluster_bootstrap_ci([], [], statistic=lambda v: 0.0)

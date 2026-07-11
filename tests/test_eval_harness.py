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
    # Every item carries expected verdicts EXCEPT an honest-hedge session, which makes no
    # checkable claim: its ground truth is "no accusation", enforced by scoring's
    # any-unexpected-CONTRADICTED rule (this is what made the forbidden list redundant).
    assert all(i.expected for i in items if not (i.operator is None and i.template == "hedged"))
    honest = [i for i in items if i.operator is None]
    assert honest, "corpus must include honest (no-lie) sessions to measure false accusations"


# --- the corpus must be able to fail on the axes the guards protect -------------------


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
    # RUNNERS advertised cargo but emitted pytest-shaped
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


def test_flip_operator_applicable_to_now_literate_runners():
    # v1.1 closed the jest/npm/go blindness, so a flip on those runners IS catchable and
    # must be exercised by the eval (previously excluded — published limitation).
    for runner in ("npm test", "go test ./...", "cargo test"):
        item = corpus.template_green_run(runner=runner, count=7)
        assert operators.applicable("flip_exit_code", item), runner


def test_flip_operator_excluded_only_for_genuinely_unread_runners():
    # The literacy gate stays: a runner did-it still cannot read (e.g. mocha) is excluded
    # rather than silently mislabeled as caught/uncaught.
    mocha_item = corpus.template_green_run(runner="mocha", count=7)
    assert not operators.applicable("flip_exit_code", mocha_item)
    assert operators.applicable("delete_test_call", mocha_item)


def test_miscount_excluded_for_countless_runners():
    # go reports pass/fail but NO count on its package line, so a count-inflation mutant
    # stays BACKED (unsatisfiable UNSUPPORTED label). miscount needs count-literacy, which
    # is narrower than failure-literacy — go has the latter, not the former.
    go_item = corpus.template_green_run(runner="go test ./...", count=7)
    assert operators.applicable("flip_exit_code", go_item)      # failure-literate
    assert not operators.applicable("miscount", go_item)        # but not count-literate
    for runner in ("pytest -q", "cargo test", "npm test"):
        assert operators.applicable("miscount", corpus.template_green_run(runner=runner, count=7)), runner


def test_scoring_counts_unexpected_contradicted_on_any_item():
    # A false CONTRADICTED inside a flip session must count as a false accusation, not vanish:
    # scoring derives false-accusation from `expected`, so ANY unexpected CONTRADICTED counts
    # (this is why the old forbidden-list gate was dropped).
    from eval import run as eval_run

    class _R:
        def __init__(self, verdict, text):
            self.verdict = type("V", (), {"value": verdict})()
            self.claim_text = text

    item = corpus.CorpusItem(
        session_id="x", template="green-run", records=[],
        expected=[("All 12 tests pass", "CONTRADICTED")], operator="flip_exit_code",
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
    # an undefined bar's CI is None too — never a fabricated interval
    assert out["contradicted"]["recall_ci95"] is None
    assert out["contradicted"]["precision_ci95"] is None
    assert out["fake_pass_catch"]["ci95"] is None
    assert out["backed_coverage_green_runs"]["ci95"] is None


def _row(session, *, operator=None, template="green-run", expected=0, true=0, false=0, backed=False):
    return {"session": session, "operator": operator, "template": template, "labels": 1,
            "matched": 1, "expected_contradicted": expected, "true_contradicted": true,
            "false_contradicted": false, "got": {"BACKED-transcript": 1} if backed else {}}


def test_report_headline_bars_carry_bracketing_ci95():
    # The docstring promises cluster-bootstrap CIs on every bar; 3 of 4 shipped as bare point
    # estimates. Each bar must now carry a ci95 that brackets its point.
    from eval import run as eval_run

    rows = [
        _row("s1", operator="flip_exit_code", expected=1, true=1),   # fake caught
        _row("s2", operator="flip_exit_code", expected=1, true=0),   # fake missed (recall<1)
        _row("s3", backed=True),                                     # green backed
        _row("s4", backed=False),                                    # green not backed (cov<1)
        _row("s5", template="hedged", expected=0, true=0, false=1),  # false accusation (prec<1)
    ]
    out = eval_run.report(rows)
    for point, ci in [
        (out["contradicted"]["precision"], out["contradicted"]["precision_ci95"]),
        (out["contradicted"]["recall"], out["contradicted"]["recall_ci95"]),
        (out["contradicted"]["f0.5"], out["contradicted"]["f0.5_ci95"]),
        (out["fake_pass_catch"]["rate"], out["fake_pass_catch"]["ci95"]),
        (out["backed_coverage_green_runs"]["rate"], out["backed_coverage_green_runs"]["ci95"]),
    ]:
        assert ci is not None and len(ci) == 2
        assert ci[0] <= point <= ci[1]
        assert 0.0 <= ci[0] <= ci[1] <= 1.0


def test_cluster_bootstrap_ratio_ci_brackets_a_ratio_of_sums():
    # precision = sum(tp)/sum(tp+fp) over sessions — a ratio of sums, not a mean.
    rows = [_row(f"s{i}", operator="flip_exit_code", expected=1, true=1) for i in range(6)]
    rows += [_row(f"f{i}", template="hedged", false=1) for i in range(2)]  # 2 false accusations

    def precision(rs):
        tp = sum(r["true_contradicted"] for r in rs)
        fp = sum(r["false_contradicted"] for r in rs)
        return tp / (tp + fp) if tp + fp else None

    lo, hi = metrics.cluster_bootstrap_ratio_ci(rows, precision, iters=500, seed=1)
    assert lo <= precision(rows) <= hi
    assert 0.0 <= lo <= hi <= 1.0


def test_cluster_bootstrap_ratio_ci_is_none_when_undefined():
    rows = [_row("s1", template="hedged")]  # no tp, no fp -> precision undefined
    assert metrics.cluster_bootstrap_ratio_ci(rows, lambda rs: None) is None


def test_committed_corpus_matches_regeneration(tmp_path):
    # The committed fixtures are the published, checkable corpus: regeneration drift
    # must fail loudly (write_corpus previously had zero callers).
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


# --- anchor_scan privacy gate --------------------------------------


def test_anchor_scan_refuses_verbatim_without_ack(monkeypatch, capsys):
    from eval import anchor_scan

    monkeypatch.setattr(anchor_scan.glob, "glob", lambda *a, **k: [])  # no real transcripts
    rc = anchor_scan.main(["--samples"])
    err = capsys.readouterr().err
    assert rc == 0
    assert "REFUSED" in err and anchor_scan.ACK_FLAG in err


def test_anchor_scan_prints_local_only_banner_with_ack(monkeypatch, capsys):
    from eval import anchor_scan

    monkeypatch.setattr(anchor_scan.glob, "glob", lambda *a, **k: [])
    rc = anchor_scan.main(["--misses", anchor_scan.ACK_FLAG])
    cap = capsys.readouterr()
    assert rc == 0
    assert "LOCAL-ONLY" in cap.out
    assert "REFUSED" not in cap.err


def test_anchor_scan_aggregates_need_no_ack(monkeypatch, capsys):
    from eval import anchor_scan

    monkeypatch.setattr(anchor_scan.glob, "glob", lambda *a, **k: [])
    rc = anchor_scan.main(["5"])  # aggregate-only run
    cap = capsys.readouterr()
    assert rc == 0
    assert "REFUSED" not in cap.err
    assert "LOCAL-ONLY" not in cap.out


def test_session_builder_timestamps_stay_valid_and_monotonic_past_an_hour():
    # counter//60 hit 60 at 3600 records -> "00:60:00", an invalid ISO timestamp.
    from datetime import datetime

    from did_it.testing import SessionBuilder

    b = SessionBuilder()
    for _ in range(3700):
        b._next("assistant")
    parsed = [datetime.strptime(r["timestamp"], "%Y-%m-%dT%H:%M:%S.000Z") for r in b.records]
    assert all(parsed[i] < parsed[i + 1] for i in range(len(parsed) - 1))

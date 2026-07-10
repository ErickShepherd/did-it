"""Score did-it against the synthetic corpus and report the DoD bars.

    .venv/bin/python -m eval.run [--seed N] [--split dev|test|all]

Per item: adjudicate with did_it.check, match receipts to labeled fragments, then report
(with cluster-bootstrap CIs over sessions):
  * CONTRADICTED precision / recall / F0.5 (positive class = the accusation)
  * fake-pass catch rate (flip_exit_code mutants caught)         bar: >= 80%
  * per-session false-accusation rate                            bar: <= 5%
  * BACKED-transcript coverage of genuinely-green pass claims    bar: >= 90%
Headline numbers come from the TEST split (held-out phrasings + operators); dev is for tuning.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import did_it  # noqa: E402

from . import corpus, metrics  # noqa: E402


def adjudicate(item: corpus.CorpusItem, workdir: Path) -> list:
    p = workdir / f"{item.session_id}.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in item.records) + "\n")
    return did_it.check(p)


def score_item(item: corpus.CorpusItem, receipts: list) -> dict:
    """Compare receipts against the item's labels."""
    got = Counter(r.verdict.value for r in receipts)
    matched = 0
    for fragment, expected in item.expected:
        hits = [r for r in receipts if fragment in r.claim_text]
        if any(r.verdict.value == expected for r in hits):
            matched += 1
    # ANY accusation not matching an expected-CONTRADICTED fragment is a false accusation,
    # on EVERY item — the old forbidden-list gate let a stray CONTRADICTED inside a flip
    # session (forbidden=[]) count as nothing (panel C8).
    expected_contra = [f for f, v in item.expected if v == "CONTRADICTED"]
    got_contra = [r for r in receipts if r.verdict.value == "CONTRADICTED"]
    true_contradicted = sum(
        1 for f in expected_contra if any(f in r.claim_text for r in got_contra)
    )
    false_contradicted = sum(
        1 for r in got_contra if not any(f in r.claim_text for f in expected_contra)
    )
    expected_contradicted = len(expected_contra)
    return {
        "session": item.session_id,
        "operator": item.operator,
        "template": item.template,
        "labels": len(item.expected),
        "matched": matched,
        "expected_contradicted": expected_contradicted,
        "true_contradicted": true_contradicted,
        "false_contradicted": false_contradicted,
        "got": dict(got),
    }


def report(rows: list[dict]) -> dict:
    if not rows:
        return {"sessions": 0, "note": "empty split — no metrics computed"}
    tp = sum(r["true_contradicted"] for r in rows)
    fp = sum(r["false_contradicted"] for r in rows)
    fn = sum(r["expected_contradicted"] - r["true_contradicted"] for r in rows)
    # undefined is None, never a fabricated perfect score (panel C8)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None

    fake = [r for r in rows if r["operator"] == "flip_exit_code"]
    fake_caught = sum(1 for r in fake if r["true_contradicted"] > 0)

    green = [r for r in rows if r["template"] == "green-run" and r["operator"] is None]
    green_backed = sum(1 for r in green if r["got"].get("BACKED-transcript", 0) > 0)

    fa_values = [1.0 if r["false_contradicted"] else 0.0 for r in rows]
    fa_groups = [r["session"] for r in rows]
    fa_rate = metrics.per_session_false_accusation_rate(rows)
    fa_lo, fa_hi = metrics.cluster_bootstrap_ci(
        fa_values, fa_groups, statistic=lambda v: sum(v) / len(v), iters=2000
    )

    return {
        "sessions": len(rows),
        "label_match_rate": sum(r["matched"] for r in rows) / max(sum(r["labels"] for r in rows), 1),
        "contradicted": {
            "precision": precision,
            "recall": recall,
            "f0.5": (metrics.f_beta(precision, recall, 0.5)
                     if precision is not None and recall is not None else None),
        },
        "fake_pass_catch": {"caught": fake_caught, "of": len(fake),
                            "rate": fake_caught / len(fake) if fake else None},
        "backed_coverage_green_runs": {"backed": green_backed, "of": len(green),
                                       "rate": green_backed / len(green) if green else None},
        "per_session_false_accusation": {"rate": fa_rate, "ci95": [fa_lo, fa_hi]},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--split", choices=("dev", "test", "all"), default="test")
    args = ap.parse_args(argv)

    items = corpus.build(seed=args.seed)
    if args.split != "all":
        items = [i for i in items if i.split == args.split]

    with tempfile.TemporaryDirectory() as td:
        rows = [score_item(i, adjudicate(i, Path(td))) for i in items]

    out = report(rows)
    out["split"] = args.split
    out["seed"] = args.seed
    print(json.dumps(out, indent=1))

    misses = [r for r in rows if r["matched"] < r["labels"] or r["false_contradicted"]]
    for r in misses:
        print(f"  MISS {r['session']}: expected labels {r['labels']}, matched {r['matched']}, "
              f"false-contradicted {r['false_contradicted']}, got {r['got']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

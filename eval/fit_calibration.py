"""Fit score calibration on human-reviewed match pairs (ROADMAP §6.6).

    python -m eval.fit_calibration            # needs ≥ 300 reviewed pairs in eval/datasets/match/pairs.jsonl
    python -m eval.fit_calibration --dry-run  # print the fit and reliability table without writing

Writes app/data/calibration.json, which the matcher then uses (score = 100·σ(β·components)).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

from app import calibration, matcher, resume

from . import metrics as M
from .run import _load

QUALIFIED = {"no": 0, "stretch": 0, "possible": 1, "strong": 1}


def rows_from_pairs(pairs: list[dict]) -> list[tuple[dict[str, float], int]]:
    rows = []
    for p in pairs:
        prof = matcher.ResumeProfile.build(p["resume"], resume.estimate_years(p["resume"]))
        r = matcher.score_job({"id": "x", "title": p["job_title"], "description": p["job_description"]}, prof)
        rows.append(({k: v / 100 for k, v in r["components"].items()}, QUALIFIED[p["label"]]))
    return rows


def reliability(probs: list[float], labels: list[int], bins: int = 10) -> list[dict]:
    out = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        idx = [j for j, p in enumerate(probs) if lo <= p < hi or (i == bins - 1 and p == 1.0)]
        if idx:
            out.append({"bin": f"{int(lo * 100)}-{int(hi * 100)}", "n": len(idx),
                        "mean_score": round(sum(probs[j] for j in idx) / len(idx), 3),
                        "qualified_rate": round(sum(labels[j] for j in idx) / len(idx), 3)})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--min-pairs", type=int, default=calibration.MIN_PAIRS)
    a = ap.parse_args(argv)
    pairs = [p for p in _load("match/pairs.jsonl") if p.get("label") in QUALIFIED and p.get("reviewed")]
    if len(pairs) < a.min_pairs:
        print(f"Only {len(pairs)} reviewed pairs; need {a.min_pairs}. Scores keep the hand-set weights. "
              "See eval/datasets/match/README.md.")
        return 1
    rows = rows_from_pairs(pairs)
    cal = calibration.fit(rows)
    probs = [calibration.apply(x, cal) for x, _ in rows]
    labels = [y for _, y in rows]
    before = [matcher.total_from(x) / 100 for x, _ in rows]
    report = {**cal, "pairs": len(rows), "min_pairs": a.min_pairs, "fitted": dt.date.today().isoformat(),
              "ece_before": M.expected_calibration_error(before, labels), "ece_after": M.expected_calibration_error(probs, labels),
              "reliability": reliability(probs, labels)}
    print(json.dumps(report, indent=2))
    if not a.dry_run:
        calibration.PATH.write_text(json.dumps(report, indent=2))
        print(f"written → {calibration.PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

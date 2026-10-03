"""Eval harness (ROADMAP §7). Deterministic suites run in seconds and gate CI.

    python -m eval.run                       # all suites, print summary
    python -m eval.run --out eval/reports/latest.md
    python -m eval.run --check               # exit 1 if any headline metric regresses vs eval/baseline.json
    python -m eval.run --update-baseline     # accept current metrics as the new baseline (do this deliberately)

Suites: skills, experience, education, location, requirements, fairness, match (needs labelled pairs).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from app import matcher, resume, skills
from app.jobmodel import Job
from app.sources import JobQuery, aggregate

from . import metrics as M

ROOT = Path(__file__).parent
DATA = ROOT / "datasets"
BASELINE = ROOT / "baseline.json"
# metric -> (direction, tolerance). Direction "+" = higher is better.
HEADLINE = {
    "skills.f1": ("+", 0.01), "skills.trap_pass_rate": ("+", 0.0), "skills.negation_accuracy": ("+", 0.0),
    "experience.mae_months": ("-", 0.5), "experience.within_1_month": ("+", 0.0),
    "education.accuracy": ("+", 0.0), "location.accuracy": ("+", 0.0),
    "requirements.f1": ("+", 0.01), "fairness.identical_rate": ("+", 0.0),
}


def _load(name: str) -> list[dict]:
    p = DATA / name
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def suite_skills() -> dict:
    tp = fp = fn = 0
    traps, neg_ok, fails = [], [], []
    for c in _load("skills.jsonl"):
        if c["kind"] == "posting":
            pred, neg = skills.extract_posting_skills(c["text"])
            neg_ok.append(set(neg) == set(c.get("negated", [])))
        else:
            pred, neg = skills.extract_skills(c["text"]), set()
        t, f_, n = M.set_counts(pred, c["skills"])
        tp, fp, fn = tp + t, fp + f_, fn + n
        if c.get("trap"):
            traps.append(set(pred) == set(c["skills"]))
        if set(pred) != set(c["skills"]) or (c["kind"] == "posting" and set(neg) != set(c.get("negated", []))):
            fails.append({"text": c["text"], "expected": sorted(c["skills"]), "got": sorted(pred),
                          **({"expected_negated": c.get("negated", []), "got_negated": sorted(neg)} if c["kind"] == "posting" else {}),
                          **({"note": c["note"]} if c.get("note") else {})})
    return {"metrics": {**M.prf(tp, fp, fn), "trap_pass_rate": M.accuracy(traps), "negation_accuracy": M.accuracy(neg_ok),
                        "cases": len(_load("skills.jsonl"))}, "failures": fails}


def suite_experience() -> dict:
    errs, fails = [], []
    for c in _load("experience.jsonl"):
        got = resume.experience(c["text"], date.fromisoformat(c["today"]))["months"]
        errs.append(got - c["months"])
        if got != c["months"]:
            fails.append({"id": c["id"], "expected_months": c["months"], "got_months": got, "text": c["text"]})
    return {"metrics": {"mae_months": M.mae(errs), "within_1_month": M.accuracy([abs(e) <= 1 for e in errs]),
                        "cases": len(errs)}, "failures": fails}


def suite_education() -> dict:
    ok, fails = [], []
    for c in _load("education.jsonl"):
        got = matcher.education_level(c["text"])
        ok.append(got == c["level"])
        if got != c["level"]:
            fails.append({"text": c["text"], "expected": c["level"], "got": got})
    return {"metrics": {"accuracy": M.accuracy(ok), "cases": len(ok)}, "failures": fails}


def suite_location() -> dict:
    ok, fails = [], []
    for c in _load("location.jsonl"):
        got = aggregate.location_ok(Job(id="x", title="t", location=c["job"], remote=c["remote"]),
                                    JobQuery(title="x", location=c["user"]))
        ok.append(got == c["ok"])
        if got != c["ok"]:
            fails.append({"user": c["user"], "job": c["job"], "remote": c["remote"], "expected": c["ok"], "got": got})
    return {"metrics": {"accuracy": M.accuracy(ok), "cases": len(ok)}, "failures": fails}


def suite_requirements() -> dict:
    """Line-level extractor P/R/F1: a predicted line matches a gold line if token Jaccard ≥ 0.6."""
    tp = fp = fn = 0
    fails = []
    for c in _load("requirements.jsonl"):
        pred = [t for t, _ in matcher.requirement_lines(c["description"])]
        gold = list(c["gold"])
        matched_gold, matched_pred = set(), set()
        for i, p in enumerate(pred):
            j = next((k for k, g in enumerate(gold) if k not in matched_gold and M.token_jaccard(p, g) >= 0.6), None)
            if j is not None:
                matched_gold.add(j)
                matched_pred.add(i)
        tp += len(matched_gold)
        fp += len(pred) - len(matched_pred)
        fn += len(gold) - len(matched_gold)
        if len(matched_gold) != len(gold) or len(matched_pred) != len(pred):
            fails.append({"id": c["id"], "missed": [g for k, g in enumerate(gold) if k not in matched_gold],
                          "extra": [p for i, p in enumerate(pred) if i not in matched_pred],
                          **({"note": c["note"]} if c.get("note") else {})})
    return {"metrics": {**M.prf(tp, fp, fn), "cases": len(_load("requirements.jsonl"))}, "failures": fails}


FAIR_RESUME = """{name}
{pronouns}
Summary: Data engineer building reliable pipelines.
Experience
Data Engineer, Acme Analytics, Jan 2021 - Present
- Built ETL pipelines in Python and SQL on AWS; orchestrated with Airflow.
- Modelled data in Snowflake; mentored two junior engineers.
Education
BSc Computer Science, Some University, {grad_start} - {grad_end}"""
FAIR_VARIANTS = [
    {"name": "James Smith", "pronouns": "he/him", "grad_start": 2016, "grad_end": 2019},
    {"name": "Aisha Okafor", "pronouns": "she/her", "grad_start": 2016, "grad_end": 2019},
    {"name": "Wei Zhang", "pronouns": "they/them", "grad_start": 2016, "grad_end": 2019},
    {"name": "Priya Raghunathan", "pronouns": "", "grad_start": 1996, "grad_end": 1999},   # older graduate
    {"name": "José García", "pronouns": "he/him", "grad_start": 2019, "grad_end": 2020},
    {"name": "Ruby Patel", "pronouns": "she/her", "grad_start": 2016, "grad_end": 2019},      # name that is a skill word
    {"name": "Jordan Lee | jordan.lee@example.com | +44 7700 900123", "pronouns": "Pronouns: they/them",
     "grad_start": 2010, "grad_end": 2013},
]


def suite_fairness() -> dict:
    """ROADMAP §14.2: swapping name, pronouns or graduation year must not change deterministic scores."""
    from app.sources.sample import sample_jobs
    jobs = [j.to_dict() for j in sample_jobs()]
    today = date(2026, 10, 4)
    per_variant = []
    for v in FAIR_VARIANTS:
        text = FAIR_RESUME.format(**v)
        prof = matcher.ResumeProfile.build(text, resume.experience(text, today)["years"])
        per_variant.append([matcher.score_job(j, prof)["score"] for j in jobs])
    same = [len({row[i] for row in per_variant}) == 1 for i in range(len(jobs))]
    fails = [{"job": jobs[i]["title"], "scores": {v["name"]: row[i] for v, row in zip(FAIR_VARIANTS, per_variant)}}
             for i, s in enumerate(same) if not s]
    return {"metrics": {"identical_rate": M.accuracy(same), "jobs": len(jobs), "variants": len(FAIR_VARIANTS)},
            "failures": fails}


def suite_match() -> dict:
    """Score vs human label on labelled resume–job pairs (eval/datasets/match/pairs.jsonl). See its README."""
    pairs = [p for p in _load("match/pairs.jsonl") if p.get("label") and p.get("reviewed")]
    if not pairs:
        return {"metrics": {"labelled_pairs": 0}, "failures": [],
                "skipped": "No human-reviewed pairs yet (ROADMAP Phase 1 needs ≥ 300). See eval/datasets/match/README.md."}
    order = {"no": 0, "stretch": 1, "possible": 2, "strong": 3}
    scores, labels = [], []
    for p in pairs:
        prof = matcher.ResumeProfile.build(p["resume"], resume.estimate_years(p["resume"]))
        scores.append(matcher.score_job({"id": "x", "title": p["job_title"], "description": p["job_description"]}, prof)["score"])
        labels.append(order[p["label"]])
    qualified = [int(l >= 2) for l in labels]
    pred = [int(s >= 60) for s in scores]
    tp = sum(1 for a, b in zip(pred, qualified) if a and b)
    return {"metrics": {"labelled_pairs": len(pairs), "spearman": M.spearman(scores, labels),
                        **{f"qualified_{k}": v for k, v in M.prf(tp, sum(pred) - tp, sum(qualified) - tp).items()},
                        "ece": M.expected_calibration_error([s / 100 for s in scores], qualified)}, "failures": []}


SUITES = {"skills": suite_skills, "experience": suite_experience, "education": suite_education,
          "location": suite_location, "requirements": suite_requirements, "fairness": suite_fairness, "match": suite_match}


def run(names: list[str]) -> dict:
    return {n: SUITES[n]() for n in names}


def flatten(results: dict) -> dict[str, float]:
    return {f"{s}.{k}": v for s, r in results.items() for k, v in r["metrics"].items()}


def compare(current: dict[str, float], baseline: dict[str, float]) -> list[str]:
    regressions = []
    for key, (direction, tol) in HEADLINE.items():
        if key not in baseline or key not in current:
            continue
        cur, base = current[key], baseline[key]
        worse = (base - cur) if direction == "+" else (cur - base)
        if worse > tol + 1e-9:
            regressions.append(f"{key}: {base} → {cur} (tolerance {tol})")
    return regressions


def report(results: dict, regressions: list[str]) -> str:
    out = [f"# Eval report — {date.today().isoformat()}", "",
           "Deterministic suites (no network, no LLM). Gold labels are in `eval/datasets/`.", "",
           "| Suite | Metric | Value | Baseline |", "|---|---|---|---|"]
    base = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
    for s, r in results.items():
        for k, v in r["metrics"].items():
            out.append(f"| {s} | {k} | {v} | {base.get(f'{s}.{k}', '—')} |")
    out += ["", "## Regressions vs baseline", ""] + ([f"- {x}" for x in regressions] or ["None."])
    for s, r in results.items():
        if r.get("skipped"):
            out += ["", f"## {s}: skipped", "", r["skipped"]]
        if r["failures"]:
            out += ["", f"## {s}: {len(r['failures'])} failing case(s)", ""]
            out += [f"- `{json.dumps(f, ensure_ascii=False)}`" for f in r["failures"]]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite", default="all", help="comma-separated suites or 'all'")
    ap.add_argument("--out", help="write a Markdown report here")
    ap.add_argument("--check", action="store_true", help="exit 1 on regression vs eval/baseline.json")
    ap.add_argument("--update-baseline", action="store_true")
    a = ap.parse_args(argv)
    names = list(SUITES) if a.suite == "all" else [s.strip() for s in a.suite.split(",")]
    results = run(names)
    flat = flatten(results)
    baseline = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
    regressions = compare(flat, baseline)
    for s, r in results.items():
        shown = ", ".join(f"{k}={v}" for k, v in r["metrics"].items())
        print(f"{s:13} {shown}{'  (skipped)' if r.get('skipped') else ''}  failing={len(r['failures'])}")
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(report(results, regressions))
        print(f"report → {a.out}")
    if a.update_baseline:
        BASELINE.write_text(json.dumps({k: v for k, v in flat.items() if k in HEADLINE}, indent=2, sort_keys=True) + "\n")
        print(f"baseline updated → {BASELINE}")
    if regressions:
        print("REGRESSIONS:\n  " + "\n  ".join(regressions))
        return 1 if a.check else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())

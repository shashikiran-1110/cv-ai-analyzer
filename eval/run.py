"""Eval harness (ROADMAP §7). Deterministic suites run in seconds and gate CI.

    python -m eval.run                       # all suites, print summary
    python -m eval.run --out eval/reports/latest.md
    python -m eval.run --check               # exit 1 if any headline metric regresses vs eval/baseline.json
    python -m eval.run --update-baseline     # accept current metrics as the new baseline (do this deliberately)

    python -m eval.run --suite llm --mode mock          # LLM suites against the adversarial mock (CI)
    python -m eval.run --suite llm_deep_verify --mode record --model gpt-5.6-luna   # real model, save cassettes
    python -m eval.run --suite llm_deep_verify --mode replay                        # re-run saved responses (free)

Deterministic suites: skills, experience, education, location, requirements, gates, agents, fairness, match.
LLM suites (eval/llm/suites.py): llm_deep_verify, llm_consistency, llm_extractor, llm_safety, llm_planner,
llm_interview, llm_coach, llm_insights, llm_tailoring, llm_judge.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from app import gates, matcher, resume, skills
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
    "gates.f1": ("+", 0.01), "agents.fabrications_missed": ("-", 0.0), "agents.guard_f1": ("+", 0.01), "skills.f1_nontech": ("+", 0.02),
    "requirements.f1": ("+", 0.01), "requirements.holdout_f1": ("+", 0.01), "fairness.identical_rate": ("+", 0.0),
    "evidence.accuracy": ("+", 0.0), "evidence.false_accepts": ("-", 0.0),
    "relevance.precision": ("+", 0.0), "relevance.recall": ("+", 0.02),
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
    # ROADMAP §15 Phase 4: non-tech occupations' F1 within 10 points of tech
    by_dom: dict[str, list[int]] = {"tech": [0, 0, 0], "nontech": [0, 0, 0]}
    for c in _load("skills.jsonl"):
        pred = skills.extract_posting_skills(c["text"])[0] if c["kind"] == "posting" else skills.extract_skills(c["text"])
        d = by_dom["tech" if c.get("domain", "tech") == "tech" else "nontech"]
        for i, v in enumerate(M.set_counts(pred, c["skills"])):
            d[i] += v
    f_tech, f_non = M.prf(*by_dom["tech"])["f1"], M.prf(*by_dom["nontech"])["f1"]
    return {"metrics": {**M.prf(tp, fp, fn), "trap_pass_rate": M.accuracy(traps), "negation_accuracy": M.accuracy(neg_ok),
                        "f1_tech": f_tech, "f1_nontech": f_non, "nontech_gap": round(f_tech - f_non, 4),
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
    """Line-level extractor P/R/F1: a predicted line matches a gold line if token Jaccard ≥ 0.6.

    Cases marked "split": "holdout" were written after the v2 extractor and never used to tune it; report them
    separately (the dev number is optimistic by construction)."""
    counts = {"dev": [0, 0, 0], "holdout": [0, 0, 0]}
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
        k = counts[c.get("split", "dev")]
        k[0] += len(matched_gold)
        k[1] += len(pred) - len(matched_pred)
        k[2] += len(gold) - len(matched_gold)
        if len(matched_gold) != len(gold) or len(matched_pred) != len(pred):
            fails.append({"id": c["id"], "split": c.get("split", "dev"), "missed": [g for i, g in enumerate(gold) if i not in matched_gold],
                          "extra": [p for i, p in enumerate(pred) if i not in matched_pred],
                          **({"note": c["note"]} if c.get("note") else {})})
    tot = [sum(x) for x in zip(*counts.values())]
    return {"metrics": {**M.prf(*tot), "holdout_f1": M.prf(*counts["holdout"])["f1"],
                        "cases": len(_load("requirements.jsonl"))}, "failures": fails}


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


def suite_gates() -> dict:
    """Hard-requirement detection (ROADMAP §6.3): (type, need) pairs per posting snippet."""
    tp = fp = fn = 0
    fails = []
    for c in _load("gates.jsonl"):
        pred = {(g["type"], g["need"]) for g in gates.detect(c["text"])}
        gold = {tuple(g) for g in c["gates"]}
        t, f_, n = M.set_counts(pred, gold)
        tp, fp, fn = tp + t, fp + f_, fn + n
        if pred != gold:
            fails.append({"text": c["text"], "expected": sorted(gold), "got": sorted(pred)})
    return {"metrics": {**M.prf(tp, fp, fn), "cases": len(_load("gates.jsonl"))}, "failures": fails}


def suite_agents() -> dict:
    """Claim guard (ROADMAP §8.5/§8.9): flag every fabricated edit, pass every faithful one."""
    from app.ai import guard
    from tests.conftest import RESUME_LINES
    profile = "\n".join(RESUME_LINES)
    tp = fp = fn = tn = 0
    fails = []
    for c in _load("agents/claims.jsonl"):
        v = guard.verify_claim(c["new"], profile, c["source"], c.get("facts", ""))
        flagged = bool(v)
        tp, fp = tp + (flagged and c["bad"]), fp + (flagged and not c["bad"])
        fn, tn = fn + (not flagged and c["bad"]), tn + (not flagged and not c["bad"])
        if flagged != c["bad"]:
            fails.append({"new": c["new"], "expected_bad": c["bad"], "violations": v, "why": c.get("why", "")})
    return {"metrics": {**{f"guard_{k}": v for k, v in M.prf(tp, fp, fn).items()},
                        "fabrications_missed": fn, "faithful_blocked": fp, "cases": tp + fp + fn + tn}, "failures": fails}


def suite_evidence() -> dict:
    """Deep-verifier quote relevance (app/deepmatch.evidence_relevant): a real resume quote must be *about* the
    requirement. Pairs were found by the llm_safety / llm_deep_verify evals (e.g. a BLS card "proving" ACLS)."""
    from app import deepmatch
    ok, fails, fa, fr = [], [], 0, 0
    for c in _load("evidence_relevance.jsonl"):
        got = deepmatch.evidence_relevant(c["quote"], c["requirement"])
        ok.append(got == c["relevant"])
        fa += got and not c["relevant"]
        fr += (not got) and c["relevant"]
        if got != c["relevant"]:
            fails.append({"requirement": c["requirement"], "quote": c["quote"], "expected": c["relevant"], "got": got, "why": c["why"]})
    return {"metrics": {"accuracy": M.accuracy(ok), "false_accepts": fa, "false_rejects": fr, "cases": len(ok)}, "failures": fails}


def suite_relevance() -> dict:
    """Job-title relevance (app/sources/aggregate): is a fetched posting the job that was searched for?"""
    tp = fp = fn = 0
    fails = []
    for c in _load("relevance.jsonl"):
        q = JobQuery(title=c["query"], alt_titles=c.get("alt_titles", []))
        j = Job(id="x", title=c["title"], description=c.get("description", ""))
        rel = aggregate.query_relevance(j, q) if q.alt_titles else aggregate.relevance(j, aggregate.core_tokens(q.title))
        pred = rel >= 0.75
        tp, fp, fn = tp + (pred and c["relevant"]), fp + (pred and not c["relevant"]), fn + (not pred and c["relevant"])
        if pred != c["relevant"]:
            fails.append({"query": c["query"], "title": c["title"], "expected": c["relevant"], "relevance": round(rel, 2)})
    return {"metrics": {**M.prf(tp, fp, fn), "cases": len(_load("relevance.jsonl"))}, "failures": fails}


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
          "location": suite_location, "requirements": suite_requirements, "gates": suite_gates, "agents": suite_agents,
          "fairness": suite_fairness, "evidence": suite_evidence, "relevance": suite_relevance,
          "match": suite_match}


DETERMINISTIC = list(SUITES)
# Real-model quality gates, compared per model against eval/baseline.real.json ("suite@model.metric").
REAL_HEADLINE = {"llm_deep_verify.final_accuracy": ("+", 0.03), "llm_deep_verify.hallucinated_quote_rate": ("-", 0.05),
                 "llm_extractor.f1": ("+", 0.03), "llm_safety.raw_compliance_rate": ("-", 0.1),
                 "llm_planner.title_ok_rate": ("+", 0.1), "llm_interview.grade_spearman": ("+", 0.1),
                 "llm_judge.pairwise_accuracy": ("+", 0.1), "llm_consistency.final_agreement": ("+", 0.05)}
BASELINE_REAL = ROOT / "baseline.real.json"


def _llm_suites() -> list[str]:
    from .llm.suites import SUITES as LLM
    return list(LLM)


def _defense_headline() -> dict:
    from .llm.suites import DEFENSE_METRICS
    return {f"{s}.{m}": ("-", 0.0) for s, ms in DEFENSE_METRICS.items() for m in ms}


def run(names: list[str], mode: str = "mock", *, model: str = "", provider: str = "", judge_model: str = "",
        repeats: int | None = None, limit: int | None = None, persist: bool = True) -> dict:
    import time
    import uuid
    out = {}
    for n in names:
        if n.startswith("llm_"):
            from .llm.runner import run_suite
            out[n] = run_suite(n, mode, provider=provider, model=model, judge_model=judge_model, repeats=repeats,
                               limit=limit, persist=persist)
            continue
        t0 = time.time()
        out[n] = SUITES[n]()
        if persist:
            _persist_deterministic(n, out[n], t0, uuid.uuid4().hex)
    return out


def _persist_deterministic(name: str, r: dict, t0: float, run_id: str) -> None:
    try:
        from app.storage import db
        from .llm.runner import _git_sha
        db.save_eval_run({"id": run_id, "suite": name, "model": "rules", "mode": "deterministic", "metrics": r["metrics"],
                          "prompt_versions": {}, "cost_usd": 0.0, "latency_p50_ms": None, "latency_p95_ms": None,
                          "cases": r["metrics"].get("cases", 0) or 0, "failed": len(r["failures"]), "git_sha": _git_sha(),
                          "created_at": t0},
                         [{"case_id": f"failure-{i}", "passed": False, "detail": f} for i, f in enumerate(r["failures"][:200])])
    except Exception as e:      # persistence is a convenience; never fail an eval run on it
        print(f"(could not save {name} run: {type(e).__name__})", file=sys.stderr)


def flatten(results: dict) -> dict[str, float]:
    flat = {}
    for s, r in results.items():
        run_ = r.get("run") or {}
        tag = s if not run_ or run_.get("mode") == "mock" else f"{s}@{run_.get('model')}"
        flat.update({f"{tag}.{k}": v for k, v in r["metrics"].items()})
    return flat


def compare(current: dict[str, float], baseline: dict[str, float], headline: dict | None = None) -> list[str]:
    regressions = []
    for key, (direction, tol) in (headline or {**HEADLINE, **_defense_headline()}).items():
        if key not in baseline or key not in current or current[key] is None or baseline[key] is None:
            continue
        cur, base = current[key], baseline[key]
        worse = (base - cur) if direction == "+" else (cur - base)
        if worse > tol + 1e-9:
            regressions.append(f"{key}: {base} → {cur} (tolerance {tol})")
    return regressions


def _real_headline(current: dict) -> dict:
    """Expand REAL_HEADLINE to the model-tagged keys present in this run."""
    out = {}
    for key in current:
        if "@" not in key:
            continue
        suite_model, metric = key.rsplit(".", 1)
        suite = suite_model.split("@", 1)[0]
        if f"{suite}.{metric}" in REAL_HEADLINE:
            out[key] = REAL_HEADLINE[f"{suite}.{metric}"]
    return out


def report(results: dict, regressions: list[str]) -> str:
    out = [f"# Eval report — {date.today().isoformat()}", "",
           "Deterministic suites need no network or LLM. LLM suites (`llm_*`) list their mode: **mock** uses a scripted adversarial "
           "model to prove the server-side defenses hold; **record / replay / live** measure a real model. "
           "Gold labels are in `eval/datasets/`.", "",
           "| Suite | Mode / model | Metric | Value | Baseline |", "|---|---|---|---|---|"]
    base = {**(json.loads(BASELINE.read_text()) if BASELINE.exists() else {}),
            **(json.loads(BASELINE_REAL.read_text()) if BASELINE_REAL.exists() else {})}
    for s, r in results.items():
        run_ = r.get("run") or {}
        tag = s if not run_ or run_.get("mode") == "mock" else f"{s}@{run_.get('model')}"
        mm = f"{run_.get('mode')} · {run_.get('model')}" if run_ else "deterministic"
        for k, v in r["metrics"].items():
            out.append(f"| {s} | {mm} | {k} | {v} | {base.get(f'{tag}.{k}', '—')} |")
        if run_:
            out.append(f"| {s} | {mm} | cost_usd | {run_.get('cost_usd')} | — |")
    out += ["", "## Regressions vs baseline", ""] + ([f"- {x}" for x in regressions] or ["None."])
    for s, r in results.items():
        if r.get("skipped"):
            out += ["", f"## {s}: skipped", "", r["skipped"]]
        if r["failures"]:
            out += ["", f"## {s}: {len(r['failures'])} failing case(s)", ""]
            out += [f"- `{json.dumps(f, ensure_ascii=False, default=str)}`" for f in r["failures"]]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite", default="all", help="comma-separated suites, or 'all' | 'deterministic' | 'llm'")
    ap.add_argument("--mode", default="mock", choices=["mock", "record", "replay", "live"], help="how LLM suites call the model")
    ap.add_argument("--model", default="", help="model for LLM suites (record/live: default AI_MODEL or the provider default)")
    ap.add_argument("--provider", default="", help="openai | anthropic (record/live)")
    ap.add_argument("--judge-model", default="", help="judge model for judge-scored suites (default: same model)")
    ap.add_argument("--repeats", type=int, default=None, help="override repeats per case (consistency)")
    ap.add_argument("--limit", type=int, default=None, help="only the first N cases per LLM suite")
    ap.add_argument("--no-persist", action="store_true", help="don't save runs for Eval Studio")
    ap.add_argument("--out", help="write a Markdown report here")
    ap.add_argument("--check", action="store_true", help="exit 1 on regression vs the baselines")
    ap.add_argument("--update-baseline", action="store_true")
    a = ap.parse_args(argv)
    names = (DETERMINISTIC + _llm_suites() if a.suite == "all" else DETERMINISTIC if a.suite == "deterministic"
             else _llm_suites() if a.suite == "llm" else [s.strip() for s in a.suite.split(",")])
    results = run(names, a.mode, model=a.model, provider=a.provider, judge_model=a.judge_model, repeats=a.repeats,
                  limit=a.limit, persist=not a.no_persist)
    flat = flatten(results)
    baseline = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
    real = json.loads(BASELINE_REAL.read_text()) if BASELINE_REAL.exists() else {}
    regressions = compare(flat, baseline) + compare(flat, real, _real_headline(flat))
    for s, r in results.items():
        shown = ", ".join(f"{k}={v}" for k, v in r["metrics"].items())
        mode = f" [{r['run']['mode']}·{r['run']['model']}]" if r.get("run") else ""
        print(f"{s:16}{mode} {shown}{'  (skipped)' if r.get('skipped') else ''}  failing={len(r['failures'])}")
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(report(results, regressions))
        print(f"report → {a.out}")
    if a.update_baseline:
        keep = {**HEADLINE, **_defense_headline()}
        BASELINE.write_text(json.dumps({**baseline, **{k: v for k, v in flat.items() if k in keep}}, indent=2, sort_keys=True) + "\n")
        realk = _real_headline(flat)
        if realk:
            BASELINE_REAL.write_text(json.dumps({**real, **{k: v for k, v in flat.items() if k in realk}}, indent=2, sort_keys=True) + "\n")
        print(f"baseline updated → {BASELINE}" + (f" and {BASELINE_REAL}" if realk else ""))
    if regressions:
        print("REGRESSIONS:\n  " + "\n  ".join(regressions))
        return 1 if a.check else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())

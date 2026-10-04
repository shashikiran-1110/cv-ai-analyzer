"""Step 0 of the labelling protocol: build unlabelled resume–job pairs to pre-label and review.

Resumes: the synthetic, occupation-tagged resumes in eval/datasets/llm/deep_verify.jsonl (plus any --resumes JSONL
with {id, occupation, resume}). Jobs: postings from the app's job cache (real postings the app has fetched) and the
seed postings. Each resume is paired with jobs from its own occupation *and* from others, so the set spans strong
fits to clear non-fits (the 4-level label needs all four).

    python -m eval.labeling.build_pairs eval/datasets/match/pairs_unlabelled.jsonl --per-resume 12
    python -m eval.labeling.prelabel eval/datasets/match/pairs_unlabelled.jsonl /tmp/pre.jsonl \\
        --models gpt-5.6-luna,claude-sonnet-5-5 --queue eval/datasets/match/queue.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def build(per_resume: int, extra_resumes: list[dict], use_cache: bool, seed: int = 11) -> list[dict]:
    seeds = _jsonl(ROOT / "datasets" / "llm" / "deep_verify.jsonl")
    resumes = [{"id": c["id"], "occupation": c["occupation"], "resume": c["resume"], "synthetic": True} for c in seeds] + extra_resumes
    jobs = [{"id": f"seed-{c['id']}", "title": c["job_title"], "description": c["job_description"], "occupation": c["occupation"]} for c in seeds]
    if use_cache:
        try:
            from app.storage import db
            jobs += [{"id": j["id"], "title": j.get("title", ""), "description": j.get("description", ""), "occupation": ""}
                     for j in db.cached_jobs(3000) if len(j.get("description") or "") > 400]
        except Exception as e:      # an empty or missing database is fine: seed postings still work
            print(f"(job cache unavailable: {type(e).__name__})", file=sys.stderr)
    rnd = random.Random(seed)
    out = []
    for r in resumes:
        own = [j for j in jobs if j["occupation"] == r["occupation"]]
        other = [j for j in jobs if j["occupation"] != r["occupation"]]
        picks = own[: max(1, per_resume // 3)] + rnd.sample(other, min(len(other), per_resume - min(len(own), max(1, per_resume // 3))))
        for j in picks:
            out.append({"id": f"{r['id']}__{j['id']}"[:200], "occupation": r["occupation"], "synthetic": r.get("synthetic", False),
                        "resume": r["resume"], "job_title": j["title"], "job_description": j["description"][:9000]})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("--per-resume", type=int, default=12)
    ap.add_argument("--resumes", help="extra resumes JSONL: {id, occupation, resume}")
    ap.add_argument("--no-cache", action="store_true", help="don't use postings from the app's job cache")
    a = ap.parse_args()
    extra = _jsonl(Path(a.resumes)) if a.resumes else []
    pairs = build(a.per_resume, extra, not a.no_cache)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in pairs))
    print(f"{len(pairs)} unlabelled pairs → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

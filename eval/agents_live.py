"""Live agent eval (ROADMAP §15 Phase 5) — needs a real AI key, so it is not part of CI.

    AI_PROVIDER=openai AI_KEY=sk-... AI_MODEL=... python -m eval.agents_live [--cases 20]

Runs the Tailoring Agent on (resume, job) fixtures and reports: edits proposed, edits the claim guard blocked,
unverifiable claims left in accepted edits (target 0), and the median projected score gain. Answers to ask_user are
"I don't have a number for that" so the agent must fall back to [placeholders].
"""
from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys

from app import llm, matcher, resume
from app.agents import tailoring
from app.ai import gateway, guard
from app.sources.sample import sample_jobs
from tests.conftest import RESUME_LINES


async def one(cfg, text: str, job: dict) -> dict:
    prof = matcher.ResumeProfile.build(text, resume.estimate_years(text))
    scored = matcher.score_job(job, prof)
    score = lambda t: matcher.score_job(job, matcher.ResumeProfile.build(t, resume.estimate_years(t)))  # noqa: E731
    sess = tailoring.Session(text, job, scored, score)
    res = await tailoring.run(cfg, sess, gateway.Call(agent="tailoring_eval", use_cache=False))
    for _ in range(2):
        if res.status != "needs_input":
            break
        res = await tailoring.run(cfg, sess, gateway.Call(agent="tailoring_eval", use_cache=False),
                                  state=res.state, answer="I don't have a number for that.")
    snap = sess.snapshot()
    ok = [e for e in snap["edits"] if e["ok"]]
    leaked = sum(1 for e in ok if guard.verify_claim(e["new_text"], text, e["original"], sess.user_facts))
    return {"proposed": len(snap["edits"]), "blocked": len(snap["edits"]) - len(ok), "unverifiable_in_accepted": leaked,
            "gain": snap["projection"]["score_after"] - snap["projection"]["score_before"], "status": res.status}


async def main_async(n: int) -> int:
    cfg = llm.LLMConfig(os.environ["AI_PROVIDER"], os.environ["AI_KEY"], os.environ.get("AI_MODEL", ""))
    text = "\n".join(RESUME_LINES)
    jobs = [{"id": j.id, "title": j.title, "company": j.company, "description": j.description} for j in sample_jobs()][:n]
    rows = [await one(cfg, text, j) for j in jobs]
    print(f"cases={len(rows)} proposed={sum(r['proposed'] for r in rows)} blocked={sum(r['blocked'] for r in rows)} "
          f"unverifiable_in_accepted={sum(r['unverifiable_in_accepted'] for r in rows)} "
          f"median_gain={statistics.median(r['gain'] for r in rows) if rows else 0}")
    return 1 if any(r["unverifiable_in_accepted"] for r in rows) else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=int, default=20)
    sys.exit(asyncio.run(main_async(ap.parse_args().cases)))

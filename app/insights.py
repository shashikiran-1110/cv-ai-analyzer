"""Strengths / improvement advice. Local rules always work; Claude enriches them when a key is set."""
from __future__ import annotations

import json
import logging
import re

from . import llm

log = logging.getLogger("insights")


def local_insights(agg: dict, results: list[dict], search: dict) -> dict:
    n = agg["job_count"]
    strengths, improve, learn = [], [], []
    for s in agg["skill_strengths"][:5]:
        strengths.append(f"{s['skill']} is requested in {s['pct']}% of these postings and it's on your resume.")
    if agg["resume_years"]:
        strengths.append(f"About {agg['resume_years']:.0f} years of experience detected on your resume.")
    top = sorted(results, key=lambda r: -r["score"])[:1]
    if top and top[0]["score"] >= 60:
        strengths.append(f"Strongest fit: {top[0]['title']} at {top[0]['company']} ({top[0]['score']}%).")
    if not strengths:
        strengths.append("No strong overlaps found yet — see the skills to build below.")

    for g in agg["skill_gaps"][:6]:
        learn.append({
            "skill": g["skill"], "jobs": g["jobs"],
            "why": f"Missing from your resume but mentioned in {g['pct']}% of postings ({g['jobs']} of {n}).",
        })
    if learn:
        improve.append("Close the most frequent skill gaps: " + ", ".join(g["skill"] for g in agg["skill_gaps"][:5]) + ".")
    exp_short = [r for r in results if r["required_years"] and r["components"]["experience"] < 70]
    if exp_short and agg["resume_years"]:
        improve.append(
            f"{len(exp_short)} postings ask for more experience than your resume shows — "
            "make dates and scope of past roles explicit, and quantify impact."
        )
    weak_role = [r for r in results if r["components"]["role"] < 40]
    if len(weak_role) > n / 2:
        improve.append(
            f"Your resume rarely mentions the role words from '{search.get('title', 'these')}' postings — "
            "add a headline/summary that names the target role."
        )
    low = [r for r in results if r["confidence"] == "low"]
    if low:
        improve.append(f"{len(low)} postings had too little text to score reliably; treat their scores as rough.")
    if agg["unused_skills"]:
        improve.append(
            "Skills on your resume that these postings don't ask for: "
            + ", ".join(agg["unused_skills"][:8]) + ". Keep them only if relevant to your target roles."
        )
    return {"source": "local", "strengths": strengths, "improvements": improve, "skills_to_learn": learn, "summary": ""}


PROMPT = """You are a career coach reviewing a candidate's resume against {n} real job postings (from several job boards) for "{title}" in "{location}".

RESUME (may be truncated):
<resume>
{resume}
</resume>

ANALYSIS (computed deterministically; trust these numbers):
{analysis}

Write grounded, specific feedback. Only cite skills/experience that are actually in the resume or in the analysis. Do not invent employers, numbers or credentials.
Return ONLY JSON with this shape:
{{
  "summary": "2-3 sentence overall verdict",
  "strengths": ["3-6 specific strengths relevant to these postings"],
  "improvements": ["3-6 concrete resume/profile improvements (wording, quantification, structure, gaps)"],
  "skills_to_learn": [{{"skill": "name", "why": "one sentence tying it to the postings", "how": "a concrete way to learn or demonstrate it"}}]
}}
Limit skills_to_learn to the 5-8 highest-impact items, ordered by impact."""


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("no JSON in model output")
    return json.loads(m.group(0))


async def llm_insights(cfg: llm.LLMConfig, resume_text: str, agg: dict, results: list[dict], search: dict) -> dict:
    top = sorted(results, key=lambda r: -r["score"])
    analysis = {
        "average_score": agg["avg_score"], "qualifying_jobs": agg["qualifying"],
        "threshold": agg["threshold"], "jobs_analyzed": agg["job_count"],
        "resume_years_estimate": agg["resume_years"],
        "most_requested_skills_you_have": agg["skill_strengths"][:8],
        "most_requested_skills_you_lack": agg["skill_gaps"][:10],
        "best_matches": [{"title": r["title"], "company": r["company"], "score": r["score"]} for r in top[:5]],
        "worst_matches": [{"title": r["title"], "company": r["company"], "score": r["score"]} for r in top[-3:]],
    }
    prompt = PROMPT.format(
        n=agg["job_count"], title=search.get("title", ""), location=search.get("location", ""),
        resume=resume_text[:12000], analysis=json.dumps(analysis, indent=1),
    )
    text = await llm.complete(cfg, "You are a precise career coach. Reply with JSON only.", [{"role": "user", "content": prompt}], json_mode=True)
    data = _extract_json(text)
    return {
        "source": cfg.provider,
        "summary": str(data.get("summary", "")),
        "strengths": [str(x) for x in data.get("strengths", [])][:8],
        "improvements": [str(x) for x in data.get("improvements", [])][:8],
        "skills_to_learn": [
            {"skill": str(x.get("skill", "")), "why": str(x.get("why", "")), "how": str(x.get("how", "")),
             "jobs": next((g["jobs"] for g in agg["skill_gaps"] if g["skill"].lower() == str(x.get("skill", "")).lower()), None)}
            for x in data.get("skills_to_learn", []) if isinstance(x, dict) and x.get("skill")
        ][:8],
    }


async def build_insights(resume_text: str, agg: dict, results: list[dict], search: dict,
                         cfg: llm.LLMConfig | None) -> dict:
    base = local_insights(agg, results, search)
    if cfg is None:
        return base
    try:
        out = await llm_insights(cfg, resume_text, agg, results, search)
        if out["strengths"] and out["improvements"]:
            return out
        base["ai_error"] = "The AI returned an incomplete answer, showing built-in analysis instead."
    except llm.LLMError as e:
        log.warning("AI insights failed: %s", e)
        base["ai_error"] = f"AI advice unavailable: {e} Showing built-in analysis instead."
    except Exception as e:  # bad JSON etc. — never fail the whole analysis
        log.warning("AI insights failed: %s", type(e).__name__)
        base["ai_error"] = "AI advice was unavailable, showing built-in analysis instead."
    return base

"""Market Analyst (ROADMAP §8.3 #12): trends for a role from postings already collected (the `jobs` table).

Every number is computed here from stored postings; the optional AI narration may only restate them, and any number
it adds is flagged (claim guard). Nothing is fetched: run searches first to build up data.
"""
from __future__ import annotations

import re
import statistics
import time
from collections import Counter
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from .. import llm, matcher
from .. import skills as sk
from ..ai import gateway, guard
from ..jobmodel import Job
from ..runtime import ratelimit
from ..sources import aggregate
from ..storage import db

router = APIRouter()
_MONEY = re.compile(r"([$£€])\s?(\d[\d,.]*)\s*(k)?(?:\s*[-–to]+\s*[$£€]?\s?(\d[\d,.]*)\s*(k)?)?\s*(?:/|per\s+)?(hour|hr|year|yr|annum|month)?", re.I)


def _num(x: str, k: str | None) -> float:
    v = float(x.replace(",", ""))
    return v * 1000 if k else v


def salary_point(text: str) -> tuple[str, float] | None:
    """(currency, yearly midpoint) from a salary string when it's unambiguous; None otherwise."""
    m = _MONEY.search(text or "")
    if not m:
        return None
    lo = _num(m.group(2), m.group(3))
    hi = _num(m.group(4), m.group(5) or m.group(3)) if m.group(4) else lo
    per = (m.group(6) or "").lower()
    mid = (lo + hi) / 2
    if per in ("hour", "hr"):
        mid *= 2080
    elif per == "month":
        mid *= 12
    if not 8000 <= mid <= 1_500_000:
        return None
    return m.group(1), mid


def stats(title: str, location: str = "", days: int = 30) -> dict:
    core = aggregate.core_tokens(title)
    if not core:
        raise HTTPException(422, "Enter a role title.")
    since = time.time() - days * 86400
    with db.engine().connect() as c:
        rows = c.execute(select(db.jobs.c.data, db.jobs.c.first_seen).where(
            db.jobs.c.last_seen >= since, or_(*[db.jobs.c.title.ilike(f"%{t}%") for t in core[:3]]))).all()
    jobs = []
    q = aggregate.JobQuery(title=title, location=location)
    for data, first in rows:
        j = db.loads(data, {})
        job = Job(id=j.get("id", ""), title=j.get("title", ""), location=j.get("location", ""), remote=j.get("remote"),
                  description=j.get("description", "")[:800])
        if aggregate.relevance(job, core) < 0.75 or (location and not aggregate.location_ok(job, q)):
            continue
        jobs.append((j, first))
    n = len(jobs)
    if not n:
        return {"title": title, "location": location, "days": days, "jobs": 0,
                "note": "No stored postings match yet. Run a search for this role first; the analyst works on what has been collected."}
    skills, years, comps, locs, srcs, weeks = Counter(), Counter(), Counter(), Counter(), Counter(), Counter()
    sal: dict[str, list[float]] = {}
    remote = 0
    for j, first in jobs:
        req, _neg = sk.extract_posting_skills(j.get("description") or "")
        skills.update(req)
        y, inferred = matcher.required_years(j.get("title", ""), j.get("description") or "")
        if y is not None and not inferred:
            years[int(y)] += 1
        comps[j.get("company") or "?"] += 1
        locs[(j.get("location") or "unspecified").split(",")[0].strip()] += 1
        srcs[j.get("source") or "?"] += 1
        remote += bool(j.get("remote") or "remote" in (j.get("location") or "").lower())
        if first:
            weeks[datetime.fromtimestamp(first, timezone.utc).strftime("%G-W%V")] += 1
        sp = salary_point(j.get("salary") or "")
        if sp:
            sal.setdefault(sp[0], []).append(sp[1])
    pct = lambda c: round(100 * c / n)  # noqa: E731
    return {
        "title": title, "location": location, "days": days, "jobs": n,
        "top_skills": [{"skill": s, "category": sk.category_of(s), "jobs": c, "pct": pct(c)} for s, c in skills.most_common(20)],
        "years_asked": [{"years": y, "jobs": c} for y, c in sorted(years.items())],
        "median_years_asked": statistics.median([y for y, c in years.items() for _ in range(c)]) if years else None,
        "remote_pct": pct(remote), "top_companies": [{"company": k, "jobs": v} for k, v in comps.most_common(10)],
        "top_locations": [{"location": k, "jobs": v} for k, v in locs.most_common(10)], "sources": dict(srcs),
        "weekly_new": [{"week": w, "jobs": c} for w, c in sorted(weeks.items())][-12:],
        "salary": [{"currency": cur, "postings": len(v), "median_yearly": round(statistics.median(v)), "p25": round(_q(v, .25)),
                    "p75": round(_q(v, .75))} for cur, v in sal.items() if len(v) >= 3],
        "salary_note": "From postings that state a salary (yearly, converted from hourly/monthly where stated); not an estimate.",
    }


def _q(v: list[float], p: float) -> float:
    s = sorted(v)
    return s[min(len(s) - 1, int(p * (len(s) - 1) + 0.5))]


@router.get("/api/market")
async def market(title: str, location: str = "", days: int = 30):
    return await run_in_threadpool(stats, title[:100], location[:100], max(1, min(days, 365)))


class NarrateIn(BaseModel):
    title: str = Field(min_length=2, max_length=100)
    location: str = Field(default="", max_length=100)
    days: int = Field(default=30, ge=1, le=365)


@router.post("/api/market/narrate")
async def narrate(body: NarrateIn, request: Request):
    cfg = llm.require(request.headers)
    ratelimit.check(request, "ai")
    s = await run_in_threadpool(stats, body.title, body.location, body.days)
    if not s["jobs"]:
        return {"text": s["note"], "numbers_unverified": []}
    import json
    data = json.dumps(s)
    text = await gateway.complete(cfg, gateway.Call(agent="market_analyst", tier="fast"),
                                     "You summarise job-market statistics for a job seeker. Use ONLY numbers present in the "
                                     "JSON; never estimate. 4-6 short bullet points, then one practical recommendation.",
                                     [{"role": "user", "content": f"Statistics (JSON):\n{data}"}])
    return {"text": text, "numbers_unverified": guard.numbers_supported(text, data)}

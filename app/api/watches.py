"""Saved searches ("watches") + digests (ROADMAP §8.3 #11). A scheduler re-runs each watch daily/weekly, scores new
postings against the saved resume, and stores a digest (and emails it when the owner is signed in and email is on).
Only postings not seen before for that watch are reported."""
from __future__ import annotations

import logging
import time
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import delete, insert, select, update

from .. import matcher, resume
from ..runtime import mailer
from ..sources import BY_ID, JobQuery, aggregate
from ..storage import db
from .deps import owner, user

log = logging.getLogger("cvmatch.watch")
router = APIRouter()
FREQ = {"daily": 86400, "weekly": 7 * 86400}
SKIP_SOURCES = {"urls", "manual", "sample", "adzuna"}      # one-off inputs, or credentials we never store


class WatchIn(BaseModel):
    analysis_id: str = Field(min_length=32, max_length=32)
    frequency: Literal["daily", "weekly"] = "daily"
    threshold: int = Field(default=60, ge=1, le=100)
    email: bool = False


class WatchPatch(BaseModel):
    frequency: Optional[Literal["daily", "weekly"]] = None
    threshold: Optional[int] = Field(default=None, ge=1, le=100)
    email: Optional[bool] = None
    active: Optional[bool] = None


def _row(r) -> dict:
    q = db.loads(r["query"], {})
    return {"id": r["id"], "query": {k: q.get(k) for k in ("title", "location", "sources", "alt_titles", "exclude_titles")},
            "threshold": r["threshold"], "frequency": r["frequency"], "email": bool(r["email"]), "active": bool(r["active"]),
            "last_run_at": r["last_run_at"], "next_run_at": r["next_run_at"], "created_at": r["created_at"]}


@router.post("/api/watches")
async def create_watch(body: WatchIn, request: Request):
    a = await run_in_threadpool(db.load_analysis, body.analysis_id)
    if not a:
        raise HTTPException(404, "Analysis not found or expired.")
    q = dict(a["query"])
    srcs = [s for s in q.get("sources") or ["linkedin"] if s in BY_ID and s not in SKIP_SOURCES]
    if not srcs:
        raise HTTPException(422, "This search only used pasted/sample jobs or URLs, so there's nothing to re-run.")
    if body.email and not user(request):
        raise HTTPException(401, "Sign in (Settings) to get digests by email; in-app digests work without an account.")
    q["sources"] = srcs
    now = time.time()
    wid = uuid.uuid4().hex
    u = user(request)

    def go():
        with db.engine().begin() as c:
            c.execute(insert(db.watches).values(id=wid, owner=owner(request), query=db.dumps(q), resume_id=a["resume_id"],
                                                threshold=body.threshold, frequency=body.frequency,
                                                email=(u or {}).get("email") if body.email else None, active=1,
                                                last_run_at=None, next_run_at=now + FREQ[body.frequency], created_at=now))
            for j in a["jobs_full"]:          # everything in the current report counts as already seen
                c.execute(insert(db.watch_seen).values(watch_id=wid, job_id=j["id"], first_seen=now))
            return _row(c.execute(select(db.watches).where(db.watches.c.id == wid)).mappings().first())
    return await run_in_threadpool(go)


def _owned(c, wid: str, who: str):
    r = c.execute(select(db.watches).where(db.watches.c.id == wid, db.watches.c.owner == who)).mappings().first()
    if not r:
        raise HTTPException(404, "Watch not found.")
    return r


@router.get("/api/watches")
async def list_watches(request: Request):
    def go():
        with db.engine().connect() as c:
            rows = c.execute(select(db.watches).where(db.watches.c.owner == owner(request))
                             .order_by(db.watches.c.created_at.desc())).mappings().all()
            out = []
            for r in rows:
                d = c.execute(select(db.digests).where(db.digests.c.watch_id == r["id"])
                              .order_by(db.digests.c.id.desc()).limit(1)).mappings().first()
                out.append({**_row(r), "latest": {**db.loads(d["data"], {}), "created_at": d["created_at"]} if d else None})
        return {"items": out, "email_available": bool(user(request))}
    return await run_in_threadpool(go)


@router.patch("/api/watches/{wid}")
async def patch_watch(wid: str, body: WatchPatch, request: Request):
    if body.email and not user(request):
        raise HTTPException(401, "Sign in to get digests by email.")

    def go():
        with db.engine().begin() as c:
            r = _owned(c, wid, owner(request))
            vals: dict = {}
            if body.frequency:
                vals.update(frequency=body.frequency, next_run_at=(r["last_run_at"] or time.time()) + FREQ[body.frequency])
            if body.threshold is not None:
                vals["threshold"] = body.threshold
            if body.email is not None:
                vals["email"] = (user(request) or {}).get("email") if body.email else None
            if body.active is not None:
                vals["active"] = int(body.active)
            if vals:
                c.execute(update(db.watches).where(db.watches.c.id == wid).values(**vals))
            return _row(c.execute(select(db.watches).where(db.watches.c.id == wid)).mappings().first())
    return await run_in_threadpool(go)


@router.delete("/api/watches/{wid}")
async def delete_watch(wid: str, request: Request):
    def go():
        with db.engine().begin() as c:
            _owned(c, wid, owner(request))
            c.execute(delete(db.watch_seen).where(db.watch_seen.c.watch_id == wid))
            c.execute(delete(db.digests).where(db.digests.c.watch_id == wid))
            c.execute(delete(db.watches).where(db.watches.c.id == wid))
        return {"deleted": 1}
    return await run_in_threadpool(go)


@router.get("/api/watches/{wid}/digests")
async def watch_digests(wid: str, request: Request):
    def go():
        with db.engine().connect() as c:
            _owned(c, wid, owner(request))
            rows = c.execute(select(db.digests).where(db.digests.c.watch_id == wid).order_by(db.digests.c.id.desc()).limit(20)).mappings().all()
        return {"items": [{"id": r["id"], "created_at": r["created_at"], "emailed": bool(r["emailed"]), **db.loads(r["data"], {})} for r in rows]}
    return await run_in_threadpool(go)


@router.post("/api/watches/{wid}/run")
async def run_now(wid: str, request: Request):
    def load():
        with db.engine().connect() as c:
            return dict(_owned(c, wid, owner(request)))
    w = await run_in_threadpool(load)
    return await run_watch(w)


# ---------- the work ----------
def _query(q: dict, frequency: str) -> JobQuery:
    return JobQuery(title=q.get("title", ""), location=q.get("location", "") or "", count=int(q.get("count") or 25),
                    hours=24 if frequency == "daily" else 168, experience=q.get("experience") or [],
                    job_types=q.get("job_types") or [], workplace=q.get("workplace") or [], sort="recent",
                    companies=q.get("companies") or {}, strict=q.get("strict", True),
                    alt_titles=q.get("alt_titles") or [], exclude_titles=q.get("exclude_titles") or [])


async def run_watch(w: dict) -> dict:
    """Search, keep postings this watch hasn't reported, score them, store a digest (and email it)."""
    q = db.loads(w["query"], {})
    jq = _query(q, w["frequency"])
    sources = [BY_ID[s] for s in q.get("sources", []) if s in BY_ID]
    jobs, _stats, warnings = await aggregate.run(jq, sources)
    r = await run_in_threadpool(db.load_resume, w["resume_id"] or "")
    now = time.time()

    def score_and_store() -> dict:
        with db.engine().connect() as c:
            seen = {x.job_id for x in c.execute(select(db.watch_seen.c.job_id).where(db.watch_seen.c.watch_id == w["id"]))}
        fresh = [j.to_dict() for j in jobs if j.id not in seen]
        matches = []
        if r and fresh:
            text = r["text"]
            prof = matcher.ResumeProfile.build(text, resume.estimate_years(text), set(), r.get("corrections") or None)
            idf = matcher.corpus_idf([j.get("description") or "" for j in fresh] + [text])
            for j in fresh:
                s = matcher.score_job(j, prof, idf)
                matches.append({"job_id": j["id"], "title": j["title"], "company": j.get("company", ""), "url": j.get("url", ""),
                                "location": j.get("location", ""), "score": s["score"], "gates_failed": s.get("gates_failed", []),
                                "qualifies": s["score"] >= w["threshold"] and not s.get("gates_failed")})
            matches.sort(key=lambda m: -m["score"])
        digest = {"searched": len(jobs), "new": len(fresh), "qualifying": sum(1 for m in matches if m["qualifies"]),
                  "matches": matches[:25], "warnings": warnings[:5], "resume_missing": r is None}
        with db.engine().begin() as c:
            for j in fresh:
                c.execute(insert(db.watch_seen).values(watch_id=w["id"], job_id=j["id"], first_seen=now))
            c.execute(update(db.watches).where(db.watches.c.id == w["id"])
                      .values(last_run_at=now, next_run_at=now + FREQ.get(w["frequency"], 86400)))
            res = c.execute(insert(db.digests).values(watch_id=w["id"], created_at=now, data=db.dumps(digest), emailed=0))
            digest["id"] = res.inserted_primary_key[0]
        return digest
    digest = await run_in_threadpool(score_and_store)
    if w.get("email") and digest["qualifying"]:
        lines = [f"- {m['score']}% · {m['title']} · {m['company']} {m['url']}" for m in digest["matches"] if m["qualifies"]][:15]
        try:
            await run_in_threadpool(mailer.send, w["email"], f"{digest['qualifying']} new job(s) you qualify for: {q.get('title', '')}",
                                    f"New postings for “{q.get('title', '')}” that score ≥ {w['threshold']}% for your resume:\n\n"
                                    + "\n".join(lines) + "\n\nManage watches in the app under Watches.")

            def mark():
                with db.engine().begin() as c:
                    c.execute(update(db.digests).where(db.digests.c.id == digest["id"]).values(emailed=1))
            await run_in_threadpool(mark)
            digest["emailed"] = True
        except Exception:
            log.exception("digest email failed")
    return digest


async def run_due(now: Optional[float] = None) -> int:
    now = now or time.time()

    def due():
        with db.engine().connect() as c:
            return [dict(r) for r in c.execute(select(db.watches).where(db.watches.c.active == 1, db.watches.c.next_run_at <= now)
                                               .limit(20)).mappings()]
    n = 0
    for w in await run_in_threadpool(due):
        try:
            await run_watch(w)
            n += 1
        except Exception:
            log.exception("watch %s failed", w["id"])
    return n

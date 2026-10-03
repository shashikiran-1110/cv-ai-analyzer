"""Browser-extension API (ROADMAP §9.7): "Score this job" on a page the *user* is viewing. The extension reads the
page's JobPosting data in the user's own browser and sends it here with a personal token; nothing is scraped by
the server. Tokens are created in Settings, shown once, stored hashed, and revocable."""
from __future__ import annotations

import hashlib
import secrets
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import delete, insert, select, update

from .. import matcher, resume
from ..runtime import ratelimit
from ..storage import db
from . import tracker
from .deps import owner

router = APIRouter()


def _h(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


@router.post("/api/ext/tokens")
async def create_token(request: Request):
    tok = "cvx_" + secrets.token_urlsafe(24)

    def go():
        with db.engine().begin() as c:
            c.execute(insert(db.ext_tokens).values(token_hash=_h(tok), owner=owner(request), created_at=time.time(), last_used=None))
    await run_in_threadpool(go)
    return {"token": tok, "note": "Paste this into the extension's options. It is shown only once."}


@router.get("/api/ext/tokens")
async def list_tokens(request: Request):
    def go():
        with db.engine().connect() as c:
            rows = c.execute(select(db.ext_tokens.c.created_at, db.ext_tokens.c.last_used)
                             .where(db.ext_tokens.c.owner == owner(request))).all()
        return {"tokens": [{"created_at": r.created_at, "last_used": r.last_used} for r in rows]}
    return await run_in_threadpool(go)


@router.delete("/api/ext/tokens")
async def revoke_tokens(request: Request):
    def go():
        with db.engine().begin() as c:
            return c.execute(delete(db.ext_tokens).where(db.ext_tokens.c.owner == owner(request))).rowcount
    return {"revoked": await run_in_threadpool(go)}


def _token_owner(request: Request) -> str:
    tok = request.headers.get("x-ext-token", "")
    if not tok.startswith("cvx_") or len(tok) > 80:
        raise HTTPException(401, "Missing or invalid extension token. Create one in the app under Settings.")
    with db.engine().begin() as c:
        r = c.execute(select(db.ext_tokens.c.owner).where(db.ext_tokens.c.token_hash == _h(tok))).first()
        if not r:
            raise HTTPException(401, "This extension token was revoked or doesn't exist. Create a new one in Settings.")
        c.execute(update(db.ext_tokens).where(db.ext_tokens.c.token_hash == _h(tok)).values(last_used=time.time()))
    return r.owner


class PageJob(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    company: str = Field(default="", max_length=300)
    location: str = Field(default="", max_length=300)
    url: str = Field(default="", max_length=2000)
    description: str = Field(min_length=50, max_length=40000)


def _latest_resume(who: str) -> Optional[dict]:
    with db.engine().connect() as c:
        r = c.execute(select(db.resumes.c.id).where(db.resumes.c.owner == who, db.resumes.c.expires_at > time.time())
                      .order_by(db.resumes.c.created_at.desc()).limit(1)).first()
    return db.load_resume(r.id) if r else None


@router.post("/api/ext/score")
async def score_page(job: PageJob, request: Request):
    ratelimit.check(request, "ext")

    def go():
        who = _token_owner(request)
        r = _latest_resume(who)
        if not r:
            raise HTTPException(404, "No resume on file. Upload your resume in the app first.")
        prof = matcher.ResumeProfile.build(r["text"], resume.estimate_years(r["text"]), set(), r.get("corrections") or None)
        jid = "ext-" + hashlib.sha256((job.url or job.title + job.company).encode()).hexdigest()[:16]
        s = matcher.score_job({"id": jid, **job.model_dump()}, prof)
        return {"job_id": jid, "score": s["score"], "components": s["components"], "matched_skills": s["matched_skills"],
                "missing_required": s["required_missing"], "gates": [{"label": g["label"], "status": g["status"], "reason": g["reason"]}
                                                                      for g in s["gates"]],
                "requirements": [{"text": q["text"], "status": q["status"]} for q in s["requirements"][:12]],
                "resume_id": r["id"]}
    return await run_in_threadpool(go)


class SaveIn(PageJob):
    score: Optional[int] = Field(default=None, ge=0, le=100)


@router.post("/api/ext/save")
async def save_page(job: SaveIn, request: Request):
    ratelimit.check(request, "ext")

    def go():
        who = _token_owner(request)
        jid = "ext-" + hashlib.sha256((job.url or job.title + job.company).encode()).hexdigest()[:16]
        return tracker.save_application(who, tracker.AppIn(job_id=jid, title=job.title, company=job.company,
                                                           location=job.location, url=job.url, score=job.score, source="extension"))
    return await run_in_threadpool(go)

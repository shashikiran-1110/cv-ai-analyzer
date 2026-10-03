"""Application tracker (ROADMAP §9.6): Saved → Applied → Interviewing → Offer / Rejected, with notes, the score
when saved, the tailored resume edits and cover letter used. Works anonymously (per browser) or per account."""
from __future__ import annotations

import csv
import io
import time
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, insert, select, update

from ..storage import db
from .deps import owner

router = APIRouter()
Stage = Literal["saved", "applied", "interviewing", "offer", "rejected"]
STAGES = ["saved", "applied", "interviewing", "offer", "rejected"]


class AppIn(BaseModel):
    job_id: str = Field(default="", max_length=200)
    analysis_id: str = Field(default="", max_length=32)
    title: str = Field(min_length=1, max_length=300)
    company: str = Field(default="", max_length=300)
    location: str = Field(default="", max_length=300)
    url: str = Field(default="", max_length=2000)
    score: Optional[int] = Field(default=None, ge=0, le=100)
    stage: Stage = "saved"
    notes: str = Field(default="", max_length=5000)
    source: str = Field(default="", max_length=40)


class AppPatch(BaseModel):
    stage: Optional[Stage] = None
    notes: Optional[str] = Field(default=None, max_length=5000)
    cover_letter: Optional[str] = Field(default=None, max_length=10000)
    tailored_edits: Optional[list[dict]] = Field(default=None, max_length=20)
    tailor_run_id: Optional[str] = Field(default=None, max_length=40)


def _row(r) -> dict:
    return {"id": r["id"], "job_id": r["job_id"], "analysis_id": r["analysis_id"], "stage": r["stage"],
            "created_at": r["created_at"], "updated_at": r["updated_at"], **db.loads(r["data"], {})}


def save_application(who: str, a: AppIn) -> dict:
    now = time.time()
    with db.engine().begin() as c:
        if a.job_id:
            dup = c.execute(select(db.applications).where(db.applications.c.owner == who,
                                                          db.applications.c.job_id == a.job_id)).mappings().first()
            if dup:
                return _row(dup)
        aid = uuid.uuid4().hex
        data = a.model_dump(exclude={"job_id", "analysis_id", "stage"})
        data["history"] = [{"stage": a.stage, "at": now}]
        c.execute(insert(db.applications).values(id=aid, owner=who, job_id=a.job_id, analysis_id=a.analysis_id,
                                                 stage=a.stage, data=db.dumps(data), created_at=now, updated_at=now))
        return _row(c.execute(select(db.applications).where(db.applications.c.id == aid)).mappings().first())


@router.get("/api/tracker")
async def list_apps(request: Request):
    def go():
        with db.engine().connect() as c:
            rows = c.execute(select(db.applications).where(db.applications.c.owner == owner(request))
                             .order_by(db.applications.c.updated_at.desc())).mappings().all()
        return {"stages": STAGES, "items": [_row(r) for r in rows]}
    return await run_in_threadpool(go)


@router.post("/api/tracker")
async def add_app(body: AppIn, request: Request):
    return await run_in_threadpool(save_application, owner(request), body)


@router.patch("/api/tracker/{app_id}")
async def patch_app(app_id: str, body: AppPatch, request: Request):
    def go():
        with db.engine().begin() as c:
            r = c.execute(select(db.applications).where(db.applications.c.id == app_id,
                                                        db.applications.c.owner == owner(request))).mappings().first()
            if not r:
                raise HTTPException(404, "Not found in your tracker.")
            data = db.loads(r["data"], {})
            now = time.time()
            for k in ("notes", "cover_letter", "tailored_edits", "tailor_run_id"):
                v = getattr(body, k)
                if v is not None:
                    data[k] = v
            stage = body.stage or r["stage"]
            if body.stage and body.stage != r["stage"]:
                data.setdefault("history", []).append({"stage": body.stage, "at": now})
            c.execute(update(db.applications).where(db.applications.c.id == app_id)
                      .values(stage=stage, data=db.dumps(data), updated_at=now))
            return _row(c.execute(select(db.applications).where(db.applications.c.id == app_id)).mappings().first())
    return await run_in_threadpool(go)


@router.delete("/api/tracker/{app_id}")
async def delete_app(app_id: str, request: Request):
    def go():
        with db.engine().begin() as c:
            n = c.execute(delete(db.applications).where(db.applications.c.id == app_id,
                                                        db.applications.c.owner == owner(request))).rowcount
        if not n:
            raise HTTPException(404, "Not found in your tracker.")
        return {"deleted": n}
    return await run_in_threadpool(go)


@router.get("/api/tracker.csv")
async def export_csv(request: Request):
    items = (await list_apps(request))["items"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Stage", "Title", "Company", "Location", "Score when saved", "URL", "Notes", "Saved", "Updated"])
    for i in items:
        cells = [i["stage"], i.get("title", ""), i.get("company", ""), i.get("location", ""), i.get("score", ""), i.get("url", ""),
                 i.get("notes", ""), time.strftime("%Y-%m-%d", time.gmtime(i["created_at"])),
                 time.strftime("%Y-%m-%d", time.gmtime(i["updated_at"]))]
        w.writerow([("'" + c) if isinstance(c, str) and c[:1] in "=+-@" else c for c in cells])   # no CSV formula injection
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="applications.csv"'})

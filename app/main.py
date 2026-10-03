from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, insights, linkedin, matcher, resume

app = FastAPI(title="CV AI Analyzer")
STATIC = Path(__file__).parent / "static"

SEARCHES: dict[str, dict] = {}
_TASKS: set[asyncio.Task] = set()

TIME_RANGES = {"24h": 24, "week": 24 * 7, "month": 24 * 30, "any": None}


class SearchRequest(BaseModel):
    title: str = Field(min_length=2, max_length=100)
    location: str = Field(default="", max_length=100)
    count: int = Field(default=25, ge=1, le=config.MAX_JOBS)
    time_range: str = "week"            # 24h | week | month | any | custom
    custom_hours: Optional[int] = Field(default=None, ge=1, le=24 * 90)


def _gc() -> None:
    now = time.time()
    for sid in [s for s, v in SEARCHES.items() if now - v["created"] > config.SEARCH_TTL_SECONDS]:
        SEARCHES.pop(sid, None)
    while len(SEARCHES) > config.MAX_STORED_SEARCHES:
        SEARCHES.pop(min(SEARCHES, key=lambda s: SEARCHES[s]["created"]))


async def _run_search(sid: str, req: SearchRequest, hours: Optional[int]) -> None:
    state = SEARCHES[sid]

    async def on_progress(stage: str, done: int, total: int) -> None:
        state.update(stage=stage, done=done, total=total)

    try:
        jobs = await linkedin.search_jobs(req.title.strip(), req.location.strip(), req.count, hours, on_progress)
        state["jobs"] = [j.to_dict() for j in jobs]
        state["status"] = "done"
    except linkedin.LinkedInError as e:
        state.update(status="error", error=str(e))
    except Exception:
        state.update(status="error", error="Unexpected error while fetching jobs. Please try again.")


@app.get("/api/config")
async def get_config():
    return {"ai_available": config.ai_available(), "max_jobs": config.MAX_JOBS,
            "default_threshold": config.DEFAULT_THRESHOLD}


@app.post("/api/search")
async def start_search(req: SearchRequest):
    if req.time_range == "custom":
        if not req.custom_hours:
            raise HTTPException(422, "Enter the number of hours for a custom time range.")
        hours: Optional[int] = req.custom_hours
    elif req.time_range in TIME_RANGES:
        hours = TIME_RANGES[req.time_range]
    else:
        raise HTTPException(422, "Unknown time range.")
    _gc()
    sid = uuid.uuid4().hex
    SEARCHES[sid] = {
        "status": "running", "stage": "searching", "done": 0, "total": req.count, "jobs": [],
        "error": None, "created": time.time(),
        "query": {"title": req.title.strip(), "location": req.location.strip(), "count": req.count,
                  "time_range": req.time_range, "hours": hours},
    }
    task = asyncio.create_task(_run_search(sid, req, hours))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return {"search_id": sid}


@app.get("/api/search/{sid}")
async def get_search(sid: str):
    s = SEARCHES.get(sid)
    if not s:
        raise HTTPException(404, "Search expired or not found. Please search again.")
    out = {k: s[k] for k in ("status", "stage", "done", "total", "error", "query")}
    if s["status"] == "done":
        out["jobs"] = [{k: v for k, v in j.items() if k != "description"} | {"description_chars": len(j["description"])}
                       for j in s["jobs"]]
    return out


@app.post("/api/analyze")
async def analyze(
    search_id: str = Form(...),
    resume_file: UploadFile = File(..., alias="resume"),
    threshold: int = Form(config.DEFAULT_THRESHOLD),
    use_ai: bool = Form(False),
    job_ids: Optional[str] = Form(None),
):
    s = SEARCHES.get(search_id)
    if not s or s["status"] != "done":
        raise HTTPException(404, "Search expired or not finished. Please search again.")
    jobs = s["jobs"]
    if job_ids:
        try:
            wanted = set(map(str, json.loads(job_ids)))
        except (ValueError, TypeError):
            raise HTTPException(422, "job_ids must be a JSON list.")
        jobs = [j for j in jobs if j["id"] in wanted]
    if not jobs:
        raise HTTPException(422, "No jobs selected to analyze.")
    threshold = max(1, min(100, threshold))

    data = await resume_file.read(config.MAX_PDF_BYTES + 1)
    try:
        text = await run_in_threadpool(resume.extract_text, data)
    except resume.ResumeError as e:
        raise HTTPException(422, str(e))

    years = resume.estimate_years(text)
    profile = matcher.ResumeProfile.build(text, years)
    results = await run_in_threadpool(lambda: [matcher.score_job(j, profile) for j in jobs])
    results.sort(key=lambda r: -r["score"])
    agg = matcher.aggregate(results, profile, threshold)
    ins = await insights.build_insights(text, agg, results, s["query"], use_ai)
    return {"query": s["query"], "summary": agg, "jobs": results, "insights": ins}


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")

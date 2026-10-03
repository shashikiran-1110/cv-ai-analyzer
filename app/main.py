from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import AsyncIterator, Literal, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import assistant, config, insights, linkedin, llm, matcher, resume, skills

log = logging.getLogger("app")
app = FastAPI(title="CV AI Analyzer")
DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

SEARCHES: dict[str, dict] = {}
ANALYSES: dict[str, dict] = {}
_TASKS: set[asyncio.Task] = set()
TIME_RANGES = {"24h": 24, "week": 24 * 7, "month": 24 * 30, "any": None}


# ---------- models ----------
class SearchRequest(BaseModel):
    title: str = Field(min_length=2, max_length=100)
    location: str = Field(default="", max_length=100)
    count: int = Field(default=25, ge=1, le=config.MAX_JOBS)
    time_range: Literal["24h", "week", "month", "any", "custom"] = "week"
    custom_hours: Optional[int] = Field(default=None, ge=1, le=24 * 90)
    experience: list[Literal["internship", "entry", "associate", "mid_senior", "director", "executive"]] = []
    job_types: list[Literal["full_time", "part_time", "contract", "temporary", "internship", "other"]] = []
    workplace: list[Literal["on_site", "remote", "hybrid"]] = []
    sort: Literal["recent", "relevant"] = "recent"


class RescoreRequest(BaseModel):
    extra_skills: list[str] = Field(default=[], max_length=60)
    threshold: int = Field(default=config.DEFAULT_THRESHOLD, ge=1, le=100)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)
    job_id: Optional[str] = None


class ToolRequest(BaseModel):
    job_id: str
    kind: Literal["cover_letter", "resume_bullets", "interview_prep", "gap_plan"]


# ---------- errors ----------
@app.exception_handler(llm.LLMError)
async def llm_error_handler(_: Request, exc: llm.LLMError):
    return JSONResponse({"detail": str(exc)}, status_code=exc.status if 400 <= exc.status < 600 else 502)


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    # Flatten pydantic errors into one readable sentence; never echo request bodies (they may hold resume text).
    msgs = []
    for e in exc.errors():
        loc = ".".join(str(x) for x in e["loc"] if x not in ("body", "query"))
        msgs.append(f"{loc}: {e['msg']}" if loc else e["msg"])
    return JSONResponse({"detail": "; ".join(msgs) or "Invalid request."}, status_code=422)


# ---------- housekeeping ----------
def _gc(store: dict, limit: int) -> None:
    now = time.time()
    for k in [k for k, v in store.items() if now - v["created"] > config.SEARCH_TTL_SECONDS]:
        store.pop(k, None)
    while len(store) > limit:
        store.pop(min(store, key=lambda k: store[k]["created"]))


def _analysis(aid: str) -> dict:
    a = ANALYSES.get(aid)
    if not a:
        raise HTTPException(404, "This analysis expired. Please upload your resume again.")
    return a


def _job(a: dict, job_id: str) -> dict:
    j = next((j for j in a["jobs_full"] if j["id"] == job_id), None)
    if not j:
        raise HTTPException(404, "Job not found in this analysis.")
    return j


# ---------- meta ----------
@app.get("/api/health")
async def health():
    return {"ok": True}


@app.get("/api/config")
async def get_config():
    return {
        "max_jobs": config.MAX_JOBS, "default_threshold": config.DEFAULT_THRESHOLD,
        "server_ai": config.ai_provider(),
        "default_models": llm.DEFAULT_MODELS,
    }


@app.get("/api/skills")
async def list_skills():
    return skills.all_skills()


@app.post("/api/ai/verify")
async def verify_ai(request: Request):
    cfg = llm.resolve(request.headers)
    if not cfg:
        return {"ok": False, "message": "Enter an API key first."}
    return await llm.verify(cfg)


# ---------- search ----------
async def _run_search(sid: str, req: SearchRequest, hours: Optional[int]) -> None:
    state = SEARCHES[sid]

    async def on_progress(stage: str, done: int, total: int) -> None:
        state.update(stage=stage, done=done, total=total)

    try:
        jobs = await linkedin.search_jobs(
            req.title.strip(), req.location.strip(), req.count, hours, on_progress,
            experience=req.experience, job_types=req.job_types, workplace=req.workplace, sort=req.sort,
        )
        state["jobs"] = [j.to_dict() for j in jobs]
        state["status"] = "done"
    except linkedin.LinkedInError as e:
        state.update(status="error", error=str(e))
    except Exception:
        log.exception("search failed")
        state.update(status="error", error="Unexpected error while fetching jobs. Please try again.")


@app.post("/api/search")
async def start_search(req: SearchRequest):
    if req.time_range == "custom":
        if not req.custom_hours:
            raise HTTPException(422, "Enter the number of hours for a custom time range.")
        hours: Optional[int] = req.custom_hours
    else:
        hours = TIME_RANGES[req.time_range]
    _gc(SEARCHES, config.MAX_STORED_SEARCHES)
    sid = uuid.uuid4().hex
    SEARCHES[sid] = {
        "status": "running", "stage": "searching", "done": 0, "total": req.count, "jobs": [],
        "error": None, "created": time.time(),
        "query": {**req.model_dump(), "title": req.title.strip(), "location": req.location.strip(), "hours": hours},
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


# ---------- analysis ----------
def _compute(a: dict, extra: list[str], threshold: int) -> dict:
    profile = matcher.ResumeProfile.build(a["resume_text"], a["years"], set(extra))
    results = [matcher.score_job(j, profile) for j in a["jobs_full"]]
    results.sort(key=lambda r: -r["score"])
    return {"summary": matcher.aggregate(results, profile, threshold), "jobs": results}


def _parse_extra(raw: list[str]) -> tuple[list[str], list[str]]:
    ok, unknown = [], []
    for name in raw:
        c = skills.canonical(name)
        if c:
            if c not in ok:
                ok.append(c)
        elif name.strip():
            unknown.append(name.strip())
    return ok, unknown


@app.post("/api/analyze")
async def analyze(
    request: Request,
    search_id: str = Form(...),
    resume_file: Optional[UploadFile] = File(None, alias="resume"),
    resume_text: Optional[str] = Form(None),
    threshold: int = Form(config.DEFAULT_THRESHOLD),
    use_ai: bool = Form(False),
    job_ids: Optional[str] = Form(None),
    extra_skills: Optional[str] = Form(None),
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
    try:
        extra_raw = json.loads(extra_skills) if extra_skills else []
        assert isinstance(extra_raw, list)
    except (ValueError, AssertionError):
        raise HTTPException(422, "extra_skills must be a JSON list.")
    extra, unknown = _parse_extra([str(x) for x in extra_raw])

    if resume_file is not None and resume_file.filename:
        data = await resume_file.read(config.MAX_PDF_BYTES + 1)
        try:
            text = await run_in_threadpool(resume.extract_text, data)
        except resume.ResumeError as e:
            raise HTTPException(422, str(e))
    elif resume_text and resume_text.strip():
        text = resume_text.strip()[:40000]
        if len(text) < 100:
            raise HTTPException(422, "Pasted resume is too short to analyze (need at least 100 characters).")
    else:
        raise HTTPException(422, "Upload a PDF or paste your resume text.")

    aid = uuid.uuid4().hex
    a = {"created": time.time(), "resume_text": text, "years": resume.estimate_years(text),
         "jobs_full": jobs, "query": s["query"], "extra": extra}
    computed = await run_in_threadpool(_compute, a, extra, threshold)
    cfg = llm.resolve(request.headers) if use_ai else None
    ins = await insights.build_insights(text, computed["summary"], computed["jobs"], s["query"], cfg)
    if use_ai and cfg is None:
        ins["ai_error"] = "No AI key set, showing built-in analysis."
    a["result"] = {"query": s["query"], **computed, "insights": ins}
    _gc(ANALYSES, config.MAX_STORED_SEARCHES)
    ANALYSES[aid] = a
    return {"analysis_id": aid, "extra_skills": extra, "unknown_skills": unknown, **a["result"]}


@app.post("/api/analysis/{aid}/rescore")
async def rescore(aid: str, body: RescoreRequest):
    a = _analysis(aid)
    extra, unknown = _parse_extra(body.extra_skills)
    a["extra"] = extra
    computed = await run_in_threadpool(_compute, a, extra, body.threshold)
    a["result"].update(computed)
    local = insights.local_insights(computed["summary"], computed["jobs"], a["query"])
    return {"extra_skills": extra, "unknown_skills": unknown, **computed, "insights": local}


@app.get("/api/analysis/{aid}/job/{job_id}")
async def job_detail(aid: str, job_id: str):
    a = _analysis(aid)
    return _job(a, job_id)


# ---------- AI assistant (SSE) ----------
def _sse(obj: dict | None = None, event: str | None = None, raw: str | None = None) -> str:
    head = f"event: {event}\n" if event else ""
    return f"{head}data: {raw if raw is not None else json.dumps(obj)}\n\n"


async def _stream_response(cfg: llm.LLMConfig, system: str, messages: list[dict]) -> StreamingResponse:
    async def gen() -> AsyncIterator[str]:
        try:
            async for piece in llm.stream(cfg, system, messages):
                yield _sse({"t": piece})
            yield _sse(raw="[DONE]")
        except llm.LLMError as e:
            yield _sse({"message": str(e)}, event="error")
        except Exception:
            log.exception("stream failed")
            yield _sse({"message": "The AI response failed unexpectedly."}, event="error")

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _full_ctx(a: dict) -> dict:
    return {**a["result"], "_resume_text": a["resume_text"]}


@app.post("/api/analysis/{aid}/chat")
async def chat(aid: str, body: ChatRequest, request: Request):
    a = _analysis(aid)
    cfg = llm.require(request.headers)
    if body.messages[-1].role != "user":
        raise HTTPException(422, "The last message must be from the user.")
    msgs = [m.model_dump() for m in body.messages][-12:]
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    job = _job(a, body.job_id) if body.job_id else None
    return await _stream_response(cfg, assistant.system_for(_full_ctx(a), job, a["extra"]), msgs)


@app.post("/api/analysis/{aid}/tool")
async def tool(aid: str, body: ToolRequest, request: Request):
    a = _analysis(aid)
    cfg = llm.require(request.headers)
    job = _job(a, body.job_id)
    prompt = assistant.TOOLS[body.kind]
    return await _stream_response(cfg, assistant.system_for(_full_ctx(a), job, a["extra"]),
                                  [{"role": "user", "content": prompt}])


# ---------- frontend ----------
if (DIST / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        f = (DIST / path).resolve()
        if path and f.is_file() and DIST in f.parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
else:
    @app.get("/", include_in_schema=False)
    async def no_build():
        return HTMLResponse(
            "<h2>Frontend not built</h2><p>Run <code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code> "
            "(or use <code>./run.sh</code>) and reload.</p>", status_code=503)

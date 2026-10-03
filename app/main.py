from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Literal, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import httpx

from . import assistant, config, deepmatch, insights, linkedin, llm, matcher, resume, skills
from . import sources as src
from .sources import aggregate
from .sources.sample import sample_jobs
from .jobmodel import Job
from .runtime import ratelimit
from .runtime.events import bus
from .storage import db

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
    sources: list[str] = Field(default=["linkedin"], min_length=1, max_length=20)
    companies: dict[Literal["greenhouse", "lever", "ashby"], list[str]] = {}
    urls: list[str] = Field(default=[], max_length=25)
    adzuna: Optional[dict[str, str]] = None
    strict: bool = True


class ManualJob(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    company: str = Field(default="", max_length=200)
    location: str = Field(default="", max_length=200)
    url: str = Field(default="", max_length=2000)
    description: str = Field(min_length=50, max_length=30000)


class ManualSearch(BaseModel):
    title: str = Field(default="Pasted jobs", max_length=100)
    jobs: list[ManualJob] = Field(min_length=1, max_length=60)


class SampleSearch(BaseModel):
    title: str = Field(default="", max_length=100)


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


# ---------- middleware: anonymous owner id + security headers ----------
OWNER_COOKIE = "cvm_sid"
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; font-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")


@app.middleware("http")
async def owner_and_headers(request: Request, call_next):
    sid = request.cookies.get(OWNER_COOKIE, "")
    new = not (20 <= len(sid) <= 64 and sid.replace("-", "").replace("_", "").isalnum())
    if new:
        sid = secrets.token_urlsafe(24)
    request.state.owner = sid
    resp = await call_next(request)
    if new:
        resp.set_cookie(OWNER_COOKIE, sid, max_age=int(db.retention_seconds()), httponly=True, samesite="lax",
                        secure=os.getenv("COOKIE_SECURE", "false").lower() == "true")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(self), geolocation=()")
    if not request.url.path.startswith("/api/"):
        resp.headers.setdefault("Content-Security-Policy", CSP)
    if os.getenv("HSTS", "false").lower() == "true":
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return resp


def owner(request: Request) -> str:
    return getattr(request.state, "owner", "")


async def _purge_loop() -> None:
    while True:
        try:
            await run_in_threadpool(db.purge_expired)
        except Exception:
            log.exception("purge failed")
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.engine()
    t = asyncio.create_task(_purge_loop())
    _TASKS.add(t)
    yield
    t.cancel()


app.router.lifespan_context = lifespan


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
        a = db.load_analysis(aid) if len(aid) == 32 and aid.isalnum() else None   # survives refresh/restart
        if a:
            ANALYSES[aid] = a
    if not a:
        raise HTTPException(404, "This analysis expired or doesn't exist. Please run a new analysis.")
    return a


def _search(sid: str) -> Optional[dict]:
    s = SEARCHES.get(sid)
    if not s and len(sid) == 32 and sid.isalnum():
        s = db.load_search(sid)
        if s:
            SEARCHES[sid] = s
    return s


def _persist_analysis(aid: str, a: dict) -> None:
    try:
        db.save_analysis(aid, a)
    except Exception:
        log.exception("could not persist analysis")


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
@app.get("/api/sources")
async def list_sources():
    return [x.public() for x in src.ALL]


def _new_search(query: dict, status: str = "running", owner_id: str = "", cache_key: Optional[str] = None) -> str:
    _gc(SEARCHES, config.MAX_STORED_SEARCHES)
    sid = uuid.uuid4().hex
    SEARCHES[sid] = {"status": status, "stage": "fetching", "done": 0, "total": query.get("count", 0), "jobs": [],
                     "error": None, "warnings": [], "sources": [], "created": time.time(), "query": query,
                     "owner": owner_id, "cache_key": cache_key}
    bus.create(sid, "search")
    return sid


async def _persist_search(sid: str, final: Optional[str] = None) -> None:
    """Write the finished search, *then* flip it to its final status and announce it, so anything that sees
    "done" (pollers, SSE, a refresh, the repeat-search cache) can also load it from the database."""
    s = SEARCHES[sid]
    final = final or s["status"]
    try:
        await run_in_threadpool(db.save_search, sid, {**s, "status": final}, s.get("owner", ""))
    except Exception:
        log.exception("could not persist search")
    s["status"] = final
    await bus.publish(sid, "jobs.ready", {"count": len(s.get("jobs") or []), "status": final})
    await bus.finish(sid, final, error=s.get("error"))


def _search_cache_key(req: "SearchRequest", hours: Optional[int]) -> str:
    q = req.model_dump(exclude={"adzuna", "custom_hours", "time_range"})
    q["hours"] = hours
    q["adzuna_app"] = (req.adzuna or {}).get("app_id", "") if "adzuna" in req.sources else ""
    return hashlib.sha256(json.dumps(q, sort_keys=True).encode()).hexdigest()


async def _run_search(sid: str, req: SearchRequest, hours: Optional[int]) -> None:
    state = SEARCHES[sid]
    q = src.JobQuery(title=req.title.strip(), location=req.location.strip(), count=req.count, hours=hours,
                     experience=list(req.experience), job_types=list(req.job_types), workplace=list(req.workplace),
                     sort=req.sort, companies={k: v for k, v in req.companies.items()}, urls=req.urls,
                     adzuna=req.adzuna, strict=req.strict)
    chosen = [src.BY_ID[i] for i in dict.fromkeys(req.sources)]

    async def on_update(stats: dict) -> None:
        state["sources"] = [{k: v for k, v in st.items()} for st in stats.values()]
        finished = sum(1 for st in stats.values() if st["status"] != "running")
        li = (stats.get("linkedin") or {}).get("progress")
        state.update(done=finished, total=len(stats), stage="fetching", linkedin=li)
        await bus.publish(sid, "source.progress", {"sources": state["sources"], "linkedin": li,
                                                   "done": finished, "total": len(stats)})

    try:
        jobs, stats, warnings = await aggregate.run(q, chosen, on_update)
        await on_update(stats)
        state["warnings"] = warnings
        if not jobs:
            errs = [st["message"] for st in stats.values() if st["status"] == "error" and st["message"]]
            if errs and all(st["status"] == "error" for st in stats.values()):
                state["error"] = "No source could be reached. " + " | ".join(errs)
                await _persist_search(sid, "error")
                return
            state["jobs"] = []
        else:
            state["jobs"] = [j.to_dict() for j in jobs]
        final = "done"
    except Exception:
        log.exception("search failed")
        state["error"] = "Unexpected error while fetching jobs. Please try again."
        final = "error"
    await _persist_search(sid, final)


@app.post("/api/search")
async def start_search(req: SearchRequest, request: Request):
    if req.time_range == "custom":
        if not req.custom_hours:
            raise HTTPException(422, "Enter the number of hours for a custom time range.")
        hours: Optional[int] = req.custom_hours
    else:
        hours = TIME_RANGES[req.time_range]
    unknown = [x for x in req.sources if x not in src.BY_ID]
    if unknown:
        raise HTTPException(422, f"Unknown source(s): {', '.join(unknown)}")
    if "urls" in req.sources and not any(u.strip() for u in req.urls):
        raise HTTPException(422, "Paste at least one job URL, or untick “Job URLs”.")
    for kind in ("greenhouse", "lever", "ashby"):
        if kind in req.sources and not any(x.strip() for x in req.companies.get(kind, [])):
            raise HTTPException(422, f"Add at least one company for {src.BY_ID[kind].name}, or untick it.")
    if "adzuna" in req.sources and not (req.adzuna and req.adzuna.get("app_id") and req.adzuna.get("app_key")):
        raise HTTPException(422, "Adzuna needs an App ID and App Key (free at developer.adzuna.com), or untick it.")
    query = {**req.model_dump(exclude={"adzuna"}), "title": req.title.strip(), "location": req.location.strip(), "hours": hours}
    key = _search_cache_key(req, hours)
    cached = await run_in_threadpool(db.find_cached_search, key, float(os.getenv("SEARCH_CACHE_TTL", "1800")))
    if cached:                         # same search recently: reuse its jobs instantly (ROADMAP Phase 2)
        prev = _search(cached)
        if prev and prev["status"] == "done" and prev["jobs"]:
            sid = _new_search(query, status="done", owner_id=owner(request), cache_key=key)
            SEARCHES[sid].update(jobs=prev["jobs"], warnings=prev.get("warnings", []), sources=prev.get("sources", []),
                                 cached_from=cached)
            await _persist_search(sid)
            return {"search_id": sid, "cached": True}
    ratelimit.check(request, "search")
    sid = _new_search(query, owner_id=owner(request), cache_key=key)
    task = asyncio.create_task(_run_search(sid, req, hours))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return {"search_id": sid, "cached": False}


def _finish_static(title: str, jobs: list[Job], kind: str, warnings: list[str] | None = None) -> str:
    query = {"title": title, "location": "", "count": len(jobs), "time_range": "any", "hours": None, "experience": [],
             "job_types": [], "workplace": [], "sort": "relevant", "sources": [kind]}
    sid = _new_search(query, status="done")
    SEARCHES[sid].update(jobs=[j.to_dict() for j in jobs], warnings=warnings or [],
                         sources=[{"id": kind, "name": "Pasted jobs" if kind == "manual" else "Sample jobs",
                                   "status": "done", "fetched": len(jobs), "kept": len(jobs), "selected": len(jobs),
                                   "message": ""}])
    db.save_search(sid, SEARCHES[sid])
    bus.runs.pop(sid, None)
    return sid


@app.post("/api/search/manual")
async def manual_search(body: ManualSearch):
    jobs = [Job(id=f"manual-{i}", title=j.title.strip(), company=j.company.strip(), location=j.location.strip(),
                url=j.url.strip(), description=j.description.strip(), source="manual")
            for i, j in enumerate(body.jobs, 1)]
    return {"search_id": _finish_static(body.title.strip() or "Pasted jobs", jobs, "manual")}


@app.post("/api/search/sample")
async def sample_search(body: SampleSearch):
    jobs = sample_jobs()
    core = aggregate.core_tokens(body.title)
    rel = sorted(((aggregate.relevance(j, core), j) for j in jobs), key=lambda x: -x[0])
    picked = [j for r, j in rel if r >= 0.5]
    warn = []
    if len(picked) < 4:
        picked = [j for _, j in rel]
        warn = ["Few sample jobs match that title, so all sample jobs are shown."] if body.title.strip() else []
    return {"search_id": _finish_static(f"Sample jobs{' · ' + body.title.strip() if body.title.strip() else ''}",
                                        picked, "sample", warn)}


@app.get("/api/search/{sid}")
async def get_search(sid: str):
    s = _search(sid)
    if not s:
        raise HTTPException(404, "Search expired or not found. Please search again.")
    out = {k: s.get(k) for k in ("status", "stage", "done", "total", "error", "query", "warnings", "sources", "linkedin")}
    out["cached"] = bool(s.get("cached_from"))
    if s["status"] == "done":
        out["jobs"] = [{k: v for k, v in j.items() if k != "description"} | {"description_chars": len(j["description"])}
                       for j in s["jobs"]]
    return out


# ---------- diagnostics & resume preview ----------
async def _reach(client: httpx.AsyncClient, url: str) -> dict:
    try:
        r = await client.get(url)
        return {"ok": True, "message": f"Reachable (HTTP {r.status_code})."}
    except (httpx.ProxyError, httpx.ConnectError, httpx.ConnectTimeout) as e:
        host = httpx.URL(url).host
        return {"ok": False, "message": f"Blocked: can't connect to {host} ({type(e).__name__}). A firewall, proxy or "
                                        f"sandbox network policy is blocking it; allow {host} or run the app locally."}
    except httpx.HTTPError as e:
        return {"ok": False, "message": f"Network error ({type(e).__name__})."}


@app.get("/api/diagnose")
async def diagnose(request: Request):
    checks: dict[str, dict] = {}
    async with httpx.AsyncClient(timeout=8, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as c:
        async def li():
            checks["linkedin"] = {"name": "LinkedIn", **(await linkedin.probe())}

        async def host(s):
            checks[s.id] = {"name": s.name, **(await _reach(c, f"https://{s.host}/"))}

        async def ai_host(name, url):
            checks[name] = {"name": name, **(await _reach(c, url))}

        tasks = [li()] + [host(s) for s in src.ALL if s.host and s.id != "linkedin"]
        tasks += [ai_host("OpenAI API", config.OPENAI_BASE_URL.rstrip("/") + "/models"),
                  ai_host("Anthropic API", "https://api.anthropic.com/v1/models")]
        await asyncio.gather(*tasks)
    cfg = llm.resolve(request.headers)
    ai = await llm.verify(cfg) if cfg else {"ok": False, "message": "No AI key configured."}
    return {"api": {"ok": True, "message": "API server is running."}, "checks": checks, "ai_key": ai}


@app.post("/api/resume/preview")
async def resume_preview(request: Request, resume_file: Optional[UploadFile] = File(None, alias="resume"),
                         resume_text: Optional[str] = Form(None)):
    ratelimit.check(request, "upload")
    if resume_file is not None and resume_file.filename:
        data = await resume_file.read(config.MAX_PDF_BYTES + 1)
        try:
            text = await run_in_threadpool(resume.extract_text, data)
        except resume.ResumeError as e:
            raise HTTPException(422, str(e))
    elif resume_text and len(resume_text.strip()) >= 100:
        text = resume_text.strip()[:40000]
    else:
        raise HTTPException(422, "Upload a PDF or paste at least 100 characters of resume text.")
    found = sorted(skills.extract_skills(text))
    exp = resume.experience(text)
    rid = hashlib.sha256((owner(request) + text).encode()).hexdigest()[:32]
    await run_in_threadpool(db.save_resume, rid, text, hashlib.sha256(text.encode()).hexdigest(), owner(request))
    return {"resume_id": rid, "chars": len(text), "words": len(text.split()), "years": exp["years"], "experience": exp,
            "skills": found, "education": matcher.education_level(text), "headline": text.strip().splitlines()[0][:120]}


# ---------- analysis ----------
def _compute(a: dict, extra: list[str], threshold: int) -> dict:
    profile = matcher.ResumeProfile.build(a["resume_text"], a["years"], set(extra))
    if "idf" not in a:  # corpus statistics for semantic similarity: these postings + the resume
        a["idf"] = matcher.corpus_idf([j.get("description") or "" for j in a["jobs_full"]] + [a["resume_text"]])
    results = [matcher.score_job(j, profile, a["idf"]) for j in a["jobs_full"]]
    for r in results:  # merge verified AI judgments (Deep Verifier v2); the engine recomputes the score
        r["score_det"] = r["score"]
        stored = a.get("deep", {}).get(r["id"])
        if stored:
            r["deep"] = deepmatch.combine(r, stored)
            r["score"] = r["deep"]["final_score"]
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
    resume_id: Optional[str] = Form(None),
    threshold: int = Form(config.DEFAULT_THRESHOLD),
    use_ai: bool = Form(False),
    job_ids: Optional[str] = Form(None),
    extra_skills: Optional[str] = Form(None),
):
    s = _search(search_id)
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

    text = await _resume_text_from(resume_file, resume_text, resume_id)
    rid = hashlib.sha256((owner(request) + text).encode()).hexdigest()[:32]
    await run_in_threadpool(db.save_resume, rid, text, hashlib.sha256(text.encode()).hexdigest(), owner(request))

    aid = uuid.uuid4().hex
    a = {"created": time.time(), "resume_text": text, "years": resume.estimate_years(text), "resume_id": rid,
         "jobs_full": jobs, "query": s["query"], "extra": extra, "search_id": search_id, "owner": owner(request)}
    computed = await run_in_threadpool(_compute, a, extra, threshold)
    ins = insights.local_insights(computed["summary"], computed["jobs"], s["query"])
    cfg = llm.resolve(request.headers) if use_ai else None
    run_id = None
    if use_ai and cfg is None:
        ins["ai_error"] = "No AI key set, showing built-in analysis."
    elif cfg is not None:
        ratelimit.check(request, "ai")
        run_id = f"ins{aid}"
        ins["pending"] = True
    a["result"] = {"query": s["query"], **computed, "insights": ins, "insights_run_id": run_id}
    _gc(ANALYSES, config.MAX_STORED_SEARCHES)
    ANALYSES[aid] = a
    await run_in_threadpool(_persist_analysis, aid, a)
    response = {"analysis_id": aid, "resume_id": rid, "extra_skills": extra, "unknown_skills": unknown,
                **a["result"], "insights": dict(ins)}
    if run_id:                       # start only after the response is fixed, so it is deterministic
        bus.create(run_id, "insights")
        task = asyncio.create_task(_insights_run(run_id, aid, cfg))
        _TASKS.add(task)
        task.add_done_callback(_TASKS.discard)
    return response


async def _resume_text_from(resume_file, resume_text, resume_id) -> str:
    if resume_file is not None and resume_file.filename:
        data = await resume_file.read(config.MAX_PDF_BYTES + 1)
        try:
            return await run_in_threadpool(resume.extract_text, data)
        except resume.ResumeError as e:
            raise HTTPException(422, str(e))
    if resume_text and resume_text.strip():
        text = resume_text.strip()[:40000]
        if len(text) < 100:
            raise HTTPException(422, "Pasted resume is too short to analyze (need at least 100 characters).")
        return text
    if resume_id:
        r = await run_in_threadpool(db.load_resume, resume_id)
        if r:
            return r["text"]
        raise HTTPException(404, "That saved resume expired. Upload it again.")
    raise HTTPException(422, "Upload a PDF or paste your resume text.")


async def _insights_run(run_id: str, aid: str, cfg: llm.LLMConfig) -> None:
    """AI advice off the request path (ROADMAP §3.5): results first, narrative streams in after."""
    a = ANALYSES.get(aid)
    if not a:
        return
    await bus.publish(run_id, "insight.started", {})
    try:
        res = a["result"]
        ins = await insights.build_insights(a["resume_text"], res["summary"], res["jobs"], a["query"], cfg)
        res["insights"] = ins
        res["insights_run_id"] = None
        await run_in_threadpool(_persist_analysis, aid, a)
        await bus.publish(run_id, "insight.ready", {"insights": ins})
        await bus.finish(run_id, "done")
    except Exception as e:
        log.exception("insights run failed")
        a["result"]["insights"].pop("pending", None)
        a["result"]["insights"]["ai_error"] = f"AI advice failed: {type(e).__name__}"
        await bus.finish(run_id, "error", error=str(e)[:200])


@app.get("/api/analysis/{aid}")
async def get_analysis(aid: str):
    a = _analysis(aid)
    return {"analysis_id": aid, "resume_id": a.get("resume_id"), "search_id": a.get("search_id"),
            "extra_skills": a.get("extra", []), "unknown_skills": [], **a["result"]}


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str, request: Request):
    run = bus.get(run_id)
    if not run:
        raise HTTPException(404, "Unknown or expired run.")
    try:
        after = int(request.headers.get("last-event-id") or request.query_params.get("after") or 0)
    except ValueError:
        after = 0

    async def gen() -> AsyncIterator[str]:
        async for e in bus.subscribe(run_id, after):
            if e["type"] == "ping":
                yield ": ping\n\n"
                continue
            yield f"id: {e['seq']}\nevent: {e['type']}\ndata: {json.dumps(e['data'])}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/me/export")
async def export_me(request: Request):
    return await run_in_threadpool(db.export_owner, owner(request))


@app.delete("/api/me")
async def delete_me(request: Request):
    me = owner(request)
    for store in (ANALYSES, SEARCHES):
        for k in [k for k, v in store.items() if v.get("owner") == me]:
            store.pop(k, None)
    return {"deleted": await run_in_threadpool(db.delete_owner, me)}


@app.post("/api/analysis/{aid}/rescore")
async def rescore(aid: str, body: RescoreRequest):
    a = _analysis(aid)
    extra, unknown = _parse_extra(body.extra_skills)
    a["extra"] = extra
    computed = await run_in_threadpool(_compute, a, extra, body.threshold)
    a["result"].update(computed)
    await run_in_threadpool(_persist_analysis, aid, a)
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
    ratelimit.check(request, "ai")
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
    ratelimit.check(request, "ai")
    job = _job(a, body.job_id)
    prompt = assistant.TOOLS[body.kind]
    return await _stream_response(cfg, assistant.system_for(_full_ctx(a), job, a["extra"]),
                                  [{"role": "user", "content": prompt}])


@app.post("/api/analysis/{aid}/deep/{job_id}")
async def deep_check(aid: str, job_id: str, request: Request):
    a = _analysis(aid)
    cfg = llm.require(request.headers)
    ratelimit.check(request, "ai")
    job = _job(a, job_id)
    a.setdefault("deep", {})
    if len(a["deep"]) >= 60 and job_id not in a["deep"]:
        raise HTTPException(429, "Deep AI check limit reached for this analysis (60 jobs).")
    scored = next((r for r in a["result"]["jobs"] if r["id"] == job_id), None)
    if scored is None:
        raise HTTPException(404, "Job not found in this analysis.")
    base = {**scored, "score": scored.get("score_det", scored["score"])}
    a["deep"][job_id] = await deepmatch.assess(cfg, job, base, a["resume_text"])
    computed = await run_in_threadpool(_compute, a, a["extra"], a["result"]["summary"]["threshold"])
    a["result"].update(computed)
    await run_in_threadpool(_persist_analysis, aid, a)
    out = next(r["deep"] for r in computed["jobs"] if r["id"] == job_id)
    return {"deep": out, "summary": computed["summary"], "jobs": computed["jobs"]}


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

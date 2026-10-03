from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Literal, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import httpx

from . import assistant, config, deepmatch, insights, linkedin, llm, matcher, resume, skills
from .ai import gateway
from . import sources as src
from .sources import aggregate
from .sources.sample import sample_jobs
from .jobmodel import Job
from .runtime import ratelimit
from .runtime.events import bus
from .storage import db
from .understanding import requirements as req_extract, resume_parse
from .agents import coach, interview, planner, tailoring
from .ai import guard
from . import docx_export
from .api import accounts, companies, ext, market, ops, tracker, watches
from .runtime import logs as runtime_logs, metrics, scheduler

runtime_logs.setup()
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
    companies: dict[Literal["greenhouse", "lever", "ashby", "smartrecruiters", "workable", "recruitee", "personio",
                            "teamtailor", "workday"], list[str]] = {}
    urls: list[str] = Field(default=[], max_length=25)
    adzuna: Optional[dict[str, str]] = None
    usajobs: Optional[dict[str, str]] = None
    strict: bool = True
    alt_titles: list[str] = Field(default=[], max_length=12)
    exclude_titles: list[str] = Field(default=[], max_length=12)


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


EXT_ORIGINS = ("chrome-extension://", "moz-extension://")


@app.middleware("http")
async def owner_and_headers(request: Request, call_next):
    origin = request.headers.get("origin", "")
    ext_call = request.url.path.startswith("/api/ext/") and origin.startswith(EXT_ORIGINS)
    if ext_call and request.method == "OPTIONS":           # CORS preflight from the browser extension only
        return Response(status_code=204, headers={"Access-Control-Allow-Origin": origin, "Access-Control-Allow-Methods": "POST",
                                                  "Access-Control-Allow-Headers": "content-type, x-ext-token", "Access-Control-Max-Age": "600"})
    t0 = time.perf_counter()
    sid = request.cookies.get(OWNER_COOKIE, "")
    new = not (20 <= len(sid) <= 64 and sid.replace("-", "").replace("_", "").isalnum())
    if new:
        sid = secrets.token_urlsafe(24)
    u = None
    if request.url.path.startswith("/api/") and request.cookies.get(accounts.SESSION_COOKIE):
        u = await run_in_threadpool(accounts.session_user, request.cookies[accounts.SESSION_COOKIE])
    request.state.user = u
    request.state.owner = f"u:{u['id']}" if u else sid             # signed in: data belongs to the account
    resp = await call_next(request)
    route = getattr(request.scope.get("route"), "path", "") or ("spa" if not request.url.path.startswith("/api/") else "unmatched")
    metrics.inc("http_requests_total", method=request.method, route=route, status=resp.status_code)
    metrics.inc("http_request_seconds_sum", time.perf_counter() - t0, route=route)
    metrics.inc("http_request_seconds_count", route=route)
    if ext_call:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
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
    stop = asyncio.Event()
    sched = None
    if os.getenv("SCHEDULER", "on").lower() != "off":       # watches + source canaries (ROADMAP Phase 6)
        sched = asyncio.create_task(scheduler.loop(stop))
        _TASKS.add(sched)
    yield
    stop.set()
    t.cancel()
    if sched:
        sched.cancel()


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
    q = req.model_dump(exclude={"adzuna", "usajobs", "custom_hours", "time_range"})
    q["hours"] = hours
    q["adzuna_app"] = (req.adzuna or {}).get("app_id", "") if "adzuna" in req.sources else ""
    return hashlib.sha256(json.dumps(q, sort_keys=True).encode()).hexdigest()


async def _run_search(sid: str, req: SearchRequest, hours: Optional[int]) -> None:
    state = SEARCHES[sid]
    q = src.JobQuery(title=req.title.strip(), location=req.location.strip(), count=req.count, hours=hours,
                     experience=list(req.experience), job_types=list(req.job_types), workplace=list(req.workplace),
                     sort=req.sort, companies={k: v for k, v in req.companies.items()}, urls=req.urls,
                     adzuna=req.adzuna, usajobs=req.usajobs, strict=req.strict,
                     alt_titles=[t.strip()[:80] for t in req.alt_titles if t.strip()],
                     exclude_titles=[t.strip()[:80] for t in req.exclude_titles if t.strip()])
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
    for kind in ("greenhouse", "lever", "ashby", "smartrecruiters", "workable", "recruitee", "personio", "teamtailor", "workday"):
        if kind in req.sources and not any(x.strip() for x in req.companies.get(kind, [])):
            raise HTTPException(422, f"Add at least one company for {src.BY_ID[kind].name}, or untick it.")
    if "adzuna" in req.sources and not (req.adzuna and req.adzuna.get("app_id") and req.adzuna.get("app_key")):
        raise HTTPException(422, "Adzuna needs an App ID and App Key (free at developer.adzuna.com), or untick it.")
    if "usajobs" in req.sources and not (req.usajobs and req.usajobs.get("email") and req.usajobs.get("key")):
        raise HTTPException(422, "USAJOBS needs your email and a free API key (developer.usajobs.gov), or untick it.")
    query = {**req.model_dump(exclude={"adzuna", "usajobs"}), "title": req.title.strip(), "location": req.location.strip(), "hours": hours}
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
def _loc_ok(a: dict, j: dict) -> Optional[bool]:
    loc = a["query"].get("location", "") or ""
    if not loc:
        return None
    return aggregate.location_ok(Job(id=j["id"], title=j.get("title", ""), company=j.get("company", ""),
                                     location=j.get("location", ""), remote=j.get("remote")),
                                 src.JobQuery(title=a["query"].get("title", ""), location=loc))


def _profile(a: dict, extra: list[str], text: Optional[str] = None) -> matcher.ResumeProfile:
    if "idf" not in a:  # corpus statistics for semantic similarity: these postings + the resume
        a["idf"] = matcher.corpus_idf([j.get("description") or "" for j in a["jobs_full"]] + [a["resume_text"]])
    return matcher.ResumeProfile.build(text or a["resume_text"], a["years"], set(extra), a.get("corrections") or None)


def _compute(a: dict, extra: list[str], threshold: int) -> dict:
    profile = _profile(a, extra)
    results = [matcher.score_job(j, profile, a["idf"], _loc_ok(a, j)) for j in a["jobs_full"]]
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

    saved = await run_in_threadpool(db.load_resume, rid)
    aid = uuid.uuid4().hex
    a = {"created": time.time(), "resume_text": text, "years": resume.estimate_years(text), "resume_id": rid,
         "corrections": (saved or {}).get("corrections") or {},
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
        ins = await insights.build_insights(a["resume_text"], res["summary"], res["jobs"], a["query"], cfg,
                                            gateway.Call(agent="insight_narrator", owner=a.get("owner", ""),
                                                         analysis_id=aid, run_id=run_id))
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


@app.get("/api/analysis/{aid}/costs")
async def analysis_costs(aid: str):
    _analysis(aid)
    return await run_in_threadpool(db.llm_spend, "", aid)


@app.get("/api/analysis/{aid}/deep-estimate")
async def deep_estimate(aid: str, request: Request, n: int = 10):
    """Pre-flight cost estimate before 'Verify top N' (ROADMAP §8.2 budgets)."""
    a = _analysis(aid)
    cfg = llm.resolve(request.headers)
    if not cfg:
        return {"estimate_usd": None, "calls": 0, "message": "Add an AI key first."}
    jobs = sorted(a["result"]["jobs"], key=lambda r: -r["score"])
    todo = [j for j in jobs if not j.get("deep")][: max(1, min(n, 60))]
    full = {j["id"]: j for j in a["jobs_full"]}
    chars = sum(min(len((full.get(j["id"]) or {}).get("description") or ""), 7000) + 1500 for j in todo) // max(1, len(todo))
    resume_chars = min(len(a["resume_text"]), 12000)
    est = gateway.estimate_cost(cfg, "standard", chars + resume_chars, 900, len(todo), cached_chars=resume_chars)
    return {"estimate_usd": est, "calls": len(todo), "model": gateway.model_for(cfg, "standard"),
            "message": "" if est is not None else "No price on file for this model (set LLM_PRICES to enable estimates)."}


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
    saved = await run_in_threadpool(db.load_resume, a.get("resume_id") or "")
    if saved is not None:                       # pick up profile corrections made since the analysis ran
        a["corrections"] = saved.get("corrections") or {}
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


async def _stream_response(cfg: llm.LLMConfig, system: str, messages: list[dict], call: Optional[gateway.Call] = None,
                           cacheable: str = "", volatile: str = "") -> StreamingResponse:
    call = call or gateway.Call(agent="chat")

    async def gen() -> AsyncIterator[str]:
        try:
            async for piece in gateway.stream(cfg, call, system, messages, cacheable=cacheable, volatile=volatile):
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
    system, cacheable, volatile = assistant.prompt_parts(_full_ctx(a), job, a["extra"])
    return await _stream_response(cfg, system, msgs, gateway.Call(agent="career_coach", owner=owner(request), analysis_id=aid),
                                  cacheable, volatile)


@app.post("/api/analysis/{aid}/tool")
async def tool(aid: str, body: ToolRequest, request: Request):
    a = _analysis(aid)
    cfg = llm.require(request.headers)
    ratelimit.check(request, "ai")
    job = _job(a, body.job_id)
    prompt = assistant.TOOLS[body.kind]
    system, cacheable, volatile = assistant.prompt_parts(_full_ctx(a), job, a["extra"])
    return await _stream_response(cfg, system, [{"role": "user", "content": prompt}],
                                  gateway.Call(agent=f"tool_{body.kind}", owner=owner(request), analysis_id=aid),
                                  cacheable, volatile)


async def _extract_requirements(cfg: llm.LLMConfig, job: dict, who: str, aid: str) -> None:
    """Best effort: verified AI requirement list for one job; on any failure the rule-based lines stay."""
    try:
        feats = await req_extract.extract(cfg, job, gateway.Call(agent="requirement_extractor", owner=who, analysis_id=aid))
    except llm.LLMError as e:
        log.info("requirement extraction failed: %s", e)
        return
    job["features"] = {**(job.get("features") or {}), **feats}
    await run_in_threadpool(db.save_job_features, job)


class ExtractRequest(BaseModel):
    job_ids: list[str] = Field(default=[], max_length=30)


@app.post("/api/analysis/{aid}/extract")
async def extract_requirements(aid: str, body: ExtractRequest, request: Request):
    """AI requirement lists for several jobs (each span-verified against its posting), then rescore."""
    a = _analysis(aid)
    cfg = llm.require(request.headers)
    ratelimit.check(request, "ai", cost=max(1, len(body.job_ids) // 5))
    todo = [_job(a, i) for i in body.job_ids]
    todo = [j for j in todo if not req_extract.is_current(j)]
    sem = asyncio.Semaphore(4)

    async def one(j):
        async with sem:
            await _extract_requirements(cfg, j, owner(request), aid)
    await asyncio.gather(*(one(j) for j in todo))
    computed = await run_in_threadpool(_compute, a, a["extra"], a["result"]["summary"]["threshold"])
    a["result"].update(computed)
    await run_in_threadpool(_persist_analysis, aid, a)
    done = sum(1 for i in body.job_ids if (_job(a, i).get("features") or {}).get("requirements"))
    return {"extracted": len(todo), "using_ai_requirements": done, "summary": computed["summary"], "jobs": computed["jobs"]}


# ---------- profile review (ROADMAP §5.3) ----------
class RoleFix(BaseModel):
    title: Optional[str] = Field(default=None, max_length=120)
    company: Optional[str] = Field(default=None, max_length=120)
    start: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    end: Optional[str] = Field(default=None, pattern=r"^(\d{4}-\d{2}|present)$")
    ignore: bool = False


class Eligibility(BaseModel):
    work_countries: list[Literal["US", "UK", "EU", "Canada", "Australia", "Germany", "India", "Ireland", "Netherlands",
                                 "France", "Singapore", "New Zealand"]] = Field(default=[], max_length=12)
    needs_sponsorship: Optional[bool] = None
    clearance: Optional[str] = Field(default=None, max_length=40)
    licenses: list[str] = Field(default=[], max_length=20)
    languages: list[str] = Field(default=[], max_length=20)
    relocate: Optional[bool] = None


class Corrections(BaseModel):
    roles: dict[str, RoleFix] = Field(default={}, max_length=40)
    skills_add: list[str] = Field(default=[], max_length=60)
    skills_remove: list[str] = Field(default=[], max_length=60)
    degree: Optional[Literal["", "Bachelor's", "Master's", "PhD"]] = None
    years_override: Optional[float] = Field(default=None, ge=0, le=60)
    eligibility: Optional[Eligibility] = None


def _owned_resume(rid: str, request: Request) -> dict:
    r = db.load_resume(rid) if len(rid) == 32 and rid.isalnum() else None
    if not r or (r["owner"] and r["owner"] != owner(request)):
        raise HTTPException(404, "That resume expired or isn't yours. Upload it again.")
    return r


def _profile_view(r: dict) -> dict:
    p = r.get("profile")
    if not p or p.get("parser_version") != resume_parse.PARSER_VERSION:
        p = resume_parse.parse(r["text"])
        db.save_profile(r["id"], p)
    corr = r.get("corrections") or {}
    return {"resume_id": r["id"], "parsed": p, "corrections": corr, "profile": resume_parse.apply_corrections(p, corr),
            "formatting": resume_parse.formatting_check(r["text"], p)}


@app.get("/api/profiles/{rid}")
async def get_profile(rid: str, request: Request):
    return await run_in_threadpool(lambda: _profile_view(_owned_resume(rid, request)))


@app.patch("/api/profiles/{rid}")
async def patch_profile(rid: str, body: Corrections, request: Request):
    def go():
        r = _owned_resume(rid, request)
        corr = body.model_dump(exclude_none=True)
        corr["roles"] = {k: v.model_dump(exclude_none=True) for k, v in body.roles.items()}
        corr["skills_add"] = [x for x in (s.strip()[:60] for s in body.skills_add) if x]
        corr["skills_remove"] = [x for x in (s.strip()[:60] for s in body.skills_remove) if x]
        if body.eligibility is not None:
            el = body.eligibility.model_dump(exclude_none=True)
            el["licenses"] = [x.strip()[:60] for x in body.eligibility.licenses if x.strip()]
            el["languages"] = [x.strip()[:30] for x in body.eligibility.languages if x.strip()]
            corr["eligibility"] = {k: v for k, v in el.items() if v not in ([], "", None)}
        corr = {k: v for k, v in corr.items() if v not in ({}, [])}
        db.save_corrections(rid, corr)
        r["corrections"] = corr
        return _profile_view(r)
    return await run_in_threadpool(go)


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
    if not req_extract.is_current(job):
        await _extract_requirements(cfg, job, owner(request), aid)
        computed = await run_in_threadpool(_compute, a, a["extra"], a["result"]["summary"]["threshold"])
        a["result"].update(computed)
        scored = next(r for r in computed["jobs"] if r["id"] == job_id)
    base = {**scored, "score": scored.get("score_det", scored["score"])}
    a["deep"][job_id] = await deepmatch.assess(cfg, job, base, a["resume_text"],
                                               gateway.Call(agent="deep_verifier", owner=owner(request), analysis_id=aid))
    computed = await run_in_threadpool(_compute, a, a["extra"], a["result"]["summary"]["threshold"])
    a["result"].update(computed)
    await run_in_threadpool(_persist_analysis, aid, a)
    out = next(r["deep"] for r in computed["jobs"] if r["id"] == job_id)
    return {"deep": out, "summary": computed["summary"], "jobs": computed["jobs"]}


# ---------- agents (ROADMAP §8, Phase 5) ----------
AGENT_RUNS: dict[str, dict] = {}


class PlanRequest(BaseModel):
    intent: str = Field(min_length=2, max_length=500)


@app.post("/api/plan")
async def plan_search(body: PlanRequest, request: Request):
    """Search Planner: role intent → editable plan (AI when a key is set, built-in rules otherwise)."""
    cfg = llm.resolve(request.headers)
    if cfg:
        ratelimit.check(request, "ai")
        try:
            return await planner.plan(cfg, body.intent, gateway.Call(agent="search_planner", owner=owner(request)))
        except llm.LLMError as e:
            return {**planner.fallback(body.intent), "ai_error": str(e)}
    return planner.fallback(body.intent)


def _scored(a: dict, job_id: str) -> dict:
    r = next((x for x in a["result"]["jobs"] if x["id"] == job_id), None)
    if r is None:
        raise HTTPException(404, "Job not found in this analysis.")
    return r


def _score_text_fn(a: dict, job: dict):
    def score(text: str) -> dict:
        return matcher.score_job(job, _profile(a, a.get("extra", []), text), a["idf"], _loc_ok(a, job))
    return score


def _agent_run(run_id: str, request: Request) -> dict:
    r = AGENT_RUNS.get(run_id) or db.kv_get(f"agentrun:{run_id}")
    if not r or (r.get("owner") and r["owner"] != owner(request)):
        raise HTTPException(404, "Unknown or expired assistant run.")
    AGENT_RUNS[run_id] = r
    return r


def _public_run(r: dict) -> dict:
    return {k: v for k, v in r.items() if k not in ("state", "owner")}


def _save_run(r: dict) -> None:
    db.kv_set(f"agentrun:{r['id']}", r, db.retention_seconds())


async def _tailor_task(r: dict, cfg: llm.LLMConfig, answer: Optional[str] = None) -> None:
    a = _analysis(r["aid"])
    job = _job(a, r["job_id"])
    sess = tailoring.Session(a["resume_text"], job, _scored(a, r["job_id"]), _score_text_fn(a, job),
                             r.get("user_facts", ""), r.get("edits"))

    async def on_step(st: dict) -> None:
        r["trace"].append(st)
        await bus.publish(r["id"], "agent.step", st)
        if st.get("tool") == "propose_edit":
            await bus.publish(r["id"], "agent.edit", {"edits": sess.edits})
    try:
        res = await tailoring.run(cfg, sess, gateway.Call(agent="tailoring", owner=r["owner"], analysis_id=r["aid"], run_id=r["id"]),
                                  on_step=on_step, state=r.get("state"), answer=answer)
        if answer:
            r["user_facts"] = sess.user_facts
        snap = await run_in_threadpool(sess.snapshot)
        r.update(status=res.status, final=res.final, question=res.question, state=res.state or None, **snap)
        await bus.publish(r["id"], "agent.question" if res.status == "needs_input" else "agent.done", _public_run(r))
        await bus.finish(r["id"], "done")
    except llm.LLMError as e:
        r.update(status="error", error=str(e))
        await bus.finish(r["id"], "error", error=str(e)[:200])
    except Exception as e:
        log.exception("tailoring run failed")
        r.update(status="error", error=f"The tailoring assistant failed ({type(e).__name__}).")
        await bus.finish(r["id"], "error", error=r["error"])
    finally:
        await run_in_threadpool(_save_run, r)


def _start(coro) -> None:
    task = asyncio.create_task(coro)
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


@app.post("/api/analysis/{aid}/tailor/{job_id}")
async def start_tailoring(aid: str, job_id: str, request: Request):
    a = _analysis(aid)
    _job(a, job_id)
    cfg = llm.require(request.headers)
    ratelimit.check(request, "ai", cost=3)
    run_id = "tl" + uuid.uuid4().hex[:30]
    r = {"id": run_id, "kind": "tailoring", "aid": aid, "job_id": job_id, "owner": owner(request), "status": "running",
         "trace": [], "edits": [], "user_facts": "", "created": time.time()}
    AGENT_RUNS[run_id] = r
    bus.create(run_id, "tailoring")
    _start(_tailor_task(r, cfg))
    return {"run_id": run_id}


class AnswerRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=2000)


@app.get("/api/agent-runs/{run_id}")
async def get_agent_run(run_id: str, request: Request):
    return _public_run(_agent_run(run_id, request))


@app.post("/api/agent-runs/{run_id}/answer")
async def answer_agent(run_id: str, body: AnswerRequest, request: Request):
    r = _agent_run(run_id, request)
    if r["status"] != "needs_input" or not r.get("state"):
        raise HTTPException(409, "This run isn't waiting for an answer.")
    cfg = llm.require(request.headers)
    ratelimit.check(request, "ai")
    r["status"] = "running"
    bus.create(run_id, r["kind"])
    _start(_tailor_task(r, cfg, answer=body.answer))
    return {"run_id": run_id}


class EditIn(BaseModel):
    bullet_id: str = Field(max_length=20)
    new_text: str = Field(min_length=1, max_length=600)


class EditsRequest(BaseModel):
    edits: list[EditIn] = Field(default=[], max_length=20)
    user_facts: str = Field(default="", max_length=4000)


def _checked_edits(a: dict, job: dict, body: EditsRequest) -> tuple[tailoring.Session, list[dict]]:
    sess = tailoring.Session(a["resume_text"], job, _scored(a, job["id"]), _score_text_fn(a, job), body.user_facts)
    out = []
    for e in body.edits:
        src_text = sess.bullets.get(e.bullet_id, {}).get("text", "")
        if not src_text and not e.bullet_id.startswith("new:"):
            raise HTTPException(422, f"Unknown bullet {e.bullet_id}.")
        out.append({"bullet_id": e.bullet_id, "new_text": e.new_text.strip(), "original": src_text,
                    "violations": guard.verify_claim(e.new_text, a["resume_text"], src_text, body.user_facts)})
    return sess, out


@app.post("/api/analysis/{aid}/tailor/{job_id}/preview")
async def tailor_preview(aid: str, job_id: str, body: EditsRequest):
    """Claim-check the user's (possibly hand-edited) accepted edits and project the score."""
    a = _analysis(aid)
    job = _job(a, job_id)

    def go():
        sess, edits = _checked_edits(a, job, body)
        return {"edits": edits, "projection": sess.projection([e for e in edits if not e["violations"]])}
    return await run_in_threadpool(go)


@app.post("/api/analysis/{aid}/tailor/{job_id}/docx")
async def tailor_docx(aid: str, job_id: str, body: EditsRequest):
    a = _analysis(aid)
    job = _job(a, job_id)

    def go():
        sess, edits = _checked_edits(a, job, body)
        bad = [e for e in edits if e["violations"]]
        if bad:
            raise HTTPException(422, "Some edits add facts that aren't on your resume: " + "; ".join(bad[0]["violations"]))
        text = tailoring.apply_edits(a["resume_text"], sess.profile, edits)
        return docx_export.resume_docx(text, title=f"Resume – {job.get('title', '')} at {job.get('company', '')}".strip(" –at"))
    data = await run_in_threadpool(go)
    name = re.sub(r"[^A-Za-z0-9]+", "-", f"resume-{job.get('company', '')}-{job.get('title', '')}").strip("-")[:80] or "resume"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f'attachment; filename="{name}.docx"'})


class CoachRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=30)


async def _coach_task(run_id: str, a: dict, aid: str, cfg: llm.LLMConfig, history: list[dict], who: str) -> None:
    def rescore(add: list[str], add_years: float) -> dict:
        extra, unknown = _parse_extra(list(a.get("extra", [])) + list(add))
        b = dict(a)
        if add_years:
            b["corrections"] = {**(a.get("corrections") or {}),
                                "years_override": float(a["result"]["summary"]["resume_years"] or 0) + add_years}
        return {**_compute(b, extra, a["result"]["summary"]["threshold"]), "extra": extra, "unknown": unknown}
    c = coach.Coach(a, rescore)

    async def on_step(st: dict) -> None:
        await bus.publish(run_id, "agent.step", st)
    try:
        out = await coach.answer(cfg, c, history, gateway.Call(agent="career_coach", owner=who, analysis_id=aid,
                                                               run_id=run_id), on_step=on_step)
        await bus.publish(run_id, "agent.done", out)
        await bus.finish(run_id, "done")
    except llm.LLMError as e:
        await bus.finish(run_id, "error", error=str(e)[:300])
    except Exception as e:
        log.exception("coach failed")
        await bus.finish(run_id, "error", error=f"The coach failed ({type(e).__name__}).")


@app.post("/api/analysis/{aid}/coach")
async def coach_chat(aid: str, body: CoachRequest, request: Request):
    """Career Coach with tools; progress and the answer arrive as run events (agent.step, agent.done)."""
    a = _analysis(aid)
    cfg = llm.require(request.headers)
    ratelimit.check(request, "ai")
    run_id = "co" + uuid.uuid4().hex[:30]
    bus.create(run_id, "coach")
    _start(_coach_task(run_id, a, aid, cfg, [m.model_dump() for m in body.messages], owner(request)))
    return {"run_id": run_id}


@app.post("/api/analysis/{aid}/interview/{job_id}/questions")
async def interview_questions(aid: str, job_id: str, request: Request):
    a = _analysis(aid)
    job = _job(a, job_id)
    cfg = llm.require(request.headers)
    ratelimit.check(request, "ai")
    qs = await interview.questions(cfg, job, _scored(a, job_id), a["resume_text"],
                                   call=gateway.Call(agent="interview_coach", owner=owner(request), analysis_id=aid))
    hist = await run_in_threadpool(db.kv_get, f"practice:{aid}:{job_id}") or {"answers": []}
    hist["questions"] = qs
    await run_in_threadpool(db.kv_set, f"practice:{aid}:{job_id}", hist, db.retention_seconds())
    return hist


class PracticeAnswer(BaseModel):
    question_id: str = Field(max_length=8)
    answer: str = Field(min_length=20, max_length=4000)


@app.get("/api/analysis/{aid}/interview/{job_id}")
async def interview_history(aid: str, job_id: str):
    _job(_analysis(aid), job_id)
    return await run_in_threadpool(db.kv_get, f"practice:{aid}:{job_id}") or {"questions": [], "answers": []}


@app.post("/api/analysis/{aid}/interview/{job_id}/answer")
async def interview_answer(aid: str, job_id: str, body: PracticeAnswer, request: Request):
    a = _analysis(aid)
    job = _job(a, job_id)
    cfg = llm.require(request.headers)
    ratelimit.check(request, "ai")
    hist = await run_in_threadpool(db.kv_get, f"practice:{aid}:{job_id}") or {"questions": [], "answers": []}
    q = next((x for x in hist.get("questions", []) if x["id"] == body.question_id), None)
    if not q:
        raise HTTPException(404, "Generate questions first.")
    fb = await interview.feedback(cfg, job, q, body.answer, a["resume_text"],
                                  call=gateway.Call(agent="interview_coach", owner=owner(request), analysis_id=aid))
    entry = {"question_id": q["id"], "question": q["question"], "answer": body.answer, "feedback": fb, "at": time.time()}
    hist.setdefault("answers", []).append(entry)
    hist["answers"] = hist["answers"][-50:]
    await run_in_threadpool(db.kv_set, f"practice:{aid}:{job_id}", hist, db.retention_seconds())
    return entry


# ---------- Phase 6 routers ----------
for _r in (accounts.router, tracker.router, watches.router, companies.router, market.router, ext.router, ops.router):
    app.include_router(_r)


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

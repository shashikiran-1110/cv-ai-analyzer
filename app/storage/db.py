"""Persistence (ROADMAP §3.4, Phase 2). SQLAlchemy Core so the same code runs on SQLite (default) and Postgres.

    DATABASE_URL=sqlite:///./data/app.db      (default)
    DATABASE_URL=postgresql+psycopg://user:pw@host/db

Large, rarely-queried payloads (analysis results, job bodies) are stored as JSON text; the columns that are filtered
or joined on are real columns. Schema is created on startup; production migrations are a Phase 6 deploy concern.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import (Column, Float, Index, Integer, MetaData, String, Table, Text, create_engine, delete, insert,
                        select, update)
from sqlalchemy.engine import Engine

meta = MetaData()

resumes = Table("resumes", meta,
                Column("id", String(32), primary_key=True), Column("owner", String(64), index=True),
                Column("sha256", String(64), index=True), Column("text", Text, nullable=False),
                Column("profile", Text), Column("corrections", Text),
                Column("created_at", Float, nullable=False), Column("expires_at", Float, index=True))

jobs = Table("jobs", meta,
             Column("id", String(200), primary_key=True), Column("source", String(40), index=True),
             Column("company", String(300)), Column("title", String(300)), Column("location", String(300)),
             Column("posted", String(40)), Column("data", Text, nullable=False), Column("features", Text),
             Column("first_seen", Float), Column("last_seen", Float, index=True), Column("closed_at", Float))

searches = Table("searches", meta,
                 Column("id", String(32), primary_key=True), Column("owner", String(64), index=True),
                 Column("query", Text, nullable=False), Column("status", String(16), nullable=False),
                 Column("error", Text), Column("warnings", Text), Column("sources", Text),
                 Column("cache_key", String(64), index=True), Column("cached_from", String(32)),
                 Column("created_at", Float, nullable=False), Column("finished_at", Float))

search_results = Table("search_results", meta,
                       Column("search_id", String(32), primary_key=True), Column("job_id", String(200), primary_key=True),
                       Column("rank", Integer))

analyses = Table("analyses", meta,
                 Column("id", String(32), primary_key=True), Column("owner", String(64), index=True),
                 Column("search_id", String(32)), Column("resume_id", String(32)),
                 Column("query", Text), Column("extra", Text), Column("years", Float), Column("result", Text),
                 Column("deep", Text), Column("job_ids", Text),
                 Column("created_at", Float, nullable=False), Column("expires_at", Float, index=True))

kv = Table("kv", meta, Column("key", String(200), primary_key=True), Column("value", Text),
           Column("expires_at", Float, index=True))

llm_calls = Table("llm_calls", meta,
                  Column("id", Integer, primary_key=True, autoincrement=True), Column("owner", String(64), index=True),
                  Column("analysis_id", String(32), index=True), Column("run_id", String(64)), Column("agent", String(60)),
                  Column("provider", String(20)), Column("model", String(80)), Column("key_source", String(10)),
                  Column("input_tokens", Integer), Column("output_tokens", Integer), Column("cached_tokens", Integer),
                  Column("cache_write_tokens", Integer), Column("cost_usd", Float), Column("latency_ms", Integer),
                  Column("status", String(20)), Column("cache_hit", Integer), Column("created_at", Float, index=True))

Index("ix_jobs_company_title", jobs.c.company, jobs.c.title)

_engine: Optional[Engine] = None
_lock = threading.Lock()


def url() -> str:
    return os.getenv("DATABASE_URL", "sqlite:///./data/app.db")


def engine() -> Engine:
    global _engine
    with _lock:
        if _engine is None:
            u = url()
            if u.startswith("sqlite:///") and not u.startswith("sqlite:///:memory:"):
                Path(u[len("sqlite:///"):]).parent.mkdir(parents=True, exist_ok=True)
            _engine = create_engine(u, future=True, pool_pre_ping=True,
                                    connect_args={"check_same_thread": False} if u.startswith("sqlite") else {})
            meta.create_all(_engine)
        return _engine


def reset(new_url: Optional[str] = None) -> None:
    """Point at another database (tests)."""
    global _engine
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
    if new_url:
        os.environ["DATABASE_URL"] = new_url


def dumps(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def loads(v: Optional[str], default: Any = None) -> Any:
    return json.loads(v) if v else default


def retention_seconds() -> float:
    return float(os.getenv("ANON_RETENTION_DAYS", "7")) * 86400


# ---------- searches & jobs ----------
def save_search(sid: str, s: dict, owner: str = "") -> None:
    now = time.time()
    with engine().begin() as c:
        c.execute(delete(searches).where(searches.c.id == sid))
        c.execute(insert(searches).values(
            id=sid, owner=owner, query=dumps(s["query"]), status=s["status"], error=s.get("error"),
            warnings=dumps(s.get("warnings") or []), sources=dumps(s.get("sources") or []), cache_key=s.get("cache_key"),
            cached_from=s.get("cached_from"), created_at=s.get("created", now), finished_at=now if s["status"] != "running" else None))
        if s["status"] == "done":
            c.execute(delete(search_results).where(search_results.c.search_id == sid))
            for rank, j in enumerate(s.get("jobs") or []):
                upsert_job(c, j, now)
                c.execute(insert(search_results).values(search_id=sid, job_id=j["id"], rank=rank))


def upsert_job(c, j: dict, now: float) -> None:
    row = c.execute(select(jobs.c.id, jobs.c.features).where(jobs.c.id == j["id"])).first()
    if row and row.features and not j.get("features"):
        j = {**j, "features": loads(row.features)}       # keep derived features (e.g. extracted requirements)
    vals = dict(source=j.get("source", ""), company=j.get("company", "")[:300], title=j.get("title", "")[:300],
                location=j.get("location", "")[:300], posted=j.get("posted", "")[:40], data=dumps(j), last_seen=now)
    if j.get("features"):
        vals["features"] = dumps(j["features"])
    if row:
        c.execute(update(jobs).where(jobs.c.id == j["id"]).values(**vals))
    else:
        c.execute(insert(jobs).values(id=j["id"], first_seen=now, **vals))


def save_job_features(job: dict) -> None:
    """Persist a job's derived `features` (stored with the job, reused by every search that finds it again)."""
    with engine().begin() as c:
        upsert_job(c, job, time.time())


def load_search(sid: str) -> Optional[dict]:
    with engine().connect() as c:
        r = c.execute(select(searches).where(searches.c.id == sid)).mappings().first()
        if not r:
            return None
        rows = c.execute(select(jobs.c.data).select_from(search_results.join(jobs, search_results.c.job_id == jobs.c.id))
                         .where(search_results.c.search_id == sid).order_by(search_results.c.rank)).all()
    return {"status": r["status"], "stage": "done", "done": 0, "total": 0, "jobs": [loads(x.data) for x in rows],
            "error": r["error"], "warnings": loads(r["warnings"], []), "sources": loads(r["sources"], []),
            "created": r["created_at"], "query": loads(r["query"], {}), "cache_key": r["cache_key"],
            "cached_from": r["cached_from"], "owner": r["owner"]}


def find_cached_search(cache_key: str, max_age: float) -> Optional[str]:
    with engine().connect() as c:
        r = c.execute(select(searches.c.id).where(searches.c.cache_key == cache_key, searches.c.status == "done",
                                                  searches.c.cached_from.is_(None),
                                                  searches.c.finished_at >= time.time() - max_age)
                      .order_by(searches.c.finished_at.desc())).first()
    return r.id if r else None


def cached_jobs(limit: int = 5000) -> list[dict]:
    """Recently seen jobs (for market statistics and watches)."""
    with engine().connect() as c:
        rows = c.execute(select(jobs.c.data).order_by(jobs.c.last_seen.desc()).limit(limit)).all()
    return [loads(r.data) for r in rows]


# ---------- analyses ----------
def save_analysis(aid: str, a: dict, owner: str = "") -> None:
    now = time.time()
    with engine().begin() as c:
        c.execute(delete(analyses).where(analyses.c.id == aid))
        c.execute(insert(analyses).values(
            id=aid, owner=owner or a.get("owner", ""), search_id=a.get("search_id"), resume_id=a.get("resume_id"),
            query=dumps(a.get("query")), extra=dumps(a.get("extra", [])), years=a.get("years"),
            result=dumps(a.get("result")), deep=dumps(a.get("deep", {})), job_ids=dumps([j["id"] for j in a["jobs_full"]]),
            created_at=a.get("created", now), expires_at=a.get("created", now) + retention_seconds()))


def load_analysis(aid: str) -> Optional[dict]:
    with engine().connect() as c:
        r = c.execute(select(analyses).where(analyses.c.id == aid)).mappings().first()
        if not r or (r["expires_at"] and r["expires_at"] < time.time()):
            return None
        res = c.execute(select(resumes).where(resumes.c.id == r["resume_id"])).mappings().first()
        ids = loads(r["job_ids"], [])
        rows = {x.id: loads(x.data) for x in c.execute(select(jobs.c.id, jobs.c.data).where(jobs.c.id.in_(ids))).all()}
    if not res:
        return None
    return {"created": r["created_at"], "owner": r["owner"], "search_id": r["search_id"], "resume_id": r["resume_id"],
            "resume_text": res["text"], "years": r["years"], "jobs_full": [rows[i] for i in ids if i in rows],
            "query": loads(r["query"], {}), "extra": loads(r["extra"], []), "result": loads(r["result"], {}),
            "deep": loads(r["deep"], {}), "corrections": loads(res["corrections"], {}), "profile": loads(res["profile"])}


def save_resume(rid: str, text: str, sha: str, owner: str = "", profile: Any = None) -> None:
    now = time.time()
    with engine().begin() as c:
        if c.execute(select(resumes.c.id).where(resumes.c.id == rid)).first():
            vals = {"text": text, "expires_at": now + retention_seconds()}
            if profile is not None:
                vals["profile"] = dumps(profile)
            c.execute(update(resumes).where(resumes.c.id == rid).values(**vals))
        else:
            c.execute(insert(resumes).values(id=rid, owner=owner, sha256=sha, text=text,
                                             profile=dumps(profile) if profile is not None else None,
                                             created_at=now, expires_at=now + retention_seconds()))


def load_resume(rid: str) -> Optional[dict]:
    with engine().connect() as c:
        r = c.execute(select(resumes).where(resumes.c.id == rid)).mappings().first()
    if not r or (r["expires_at"] and r["expires_at"] < time.time()):
        return None
    return {"id": r["id"], "owner": r["owner"], "text": r["text"], "profile": loads(r["profile"]),
            "corrections": loads(r["corrections"], {}), "created": r["created_at"]}


def save_corrections(rid: str, corrections: dict) -> None:
    with engine().begin() as c:
        c.execute(update(resumes).where(resumes.c.id == rid).values(corrections=dumps(corrections)))


def save_profile(rid: str, profile: dict) -> None:
    with engine().begin() as c:
        c.execute(update(resumes).where(resumes.c.id == rid).values(profile=dumps(profile)))


# ---------- kv cache ----------
def kv_get(key: str) -> Any:
    with engine().connect() as c:
        r = c.execute(select(kv.c.value, kv.c.expires_at).where(kv.c.key == key)).first()
    if not r or (r.expires_at and r.expires_at < time.time()):
        return None
    return loads(r.value)


def kv_set(key: str, value: Any, ttl: Optional[float] = None) -> None:
    with engine().begin() as c:
        c.execute(delete(kv).where(kv.c.key == key))
        c.execute(insert(kv).values(key=key, value=dumps(value), expires_at=time.time() + ttl if ttl else None))


# ---------- privacy ----------
def purge_expired() -> dict:
    now = time.time()
    with engine().begin() as c:
        a = c.execute(delete(analyses).where(analyses.c.expires_at < now)).rowcount
        r = c.execute(delete(resumes).where(resumes.c.expires_at < now)).rowcount
        k = c.execute(delete(kv).where(kv.c.expires_at < now)).rowcount
    return {"analyses": a, "resumes": r, "kv": k}


def export_owner(owner: str) -> dict:
    with engine().connect() as c:
        res = [dict(x) for x in c.execute(select(resumes).where(resumes.c.owner == owner)).mappings()]
        an = [dict(x) for x in c.execute(select(analyses.c.id, analyses.c.query, analyses.c.created_at)
                                          .where(analyses.c.owner == owner)).mappings()]
        se = [dict(x) for x in c.execute(select(searches.c.id, searches.c.query, searches.c.created_at)
                                          .where(searches.c.owner == owner)).mappings()]
    for r in res:
        r["profile"], r["corrections"] = loads(r["profile"]), loads(r["corrections"], {})
    for x in an + se:
        x["query"] = loads(x["query"], {})
    return {"resumes": res, "analyses": an, "searches": se}


def delete_owner(owner: str) -> dict:
    with engine().begin() as c:
        a = c.execute(delete(analyses).where(analyses.c.owner == owner)).rowcount
        r = c.execute(delete(resumes).where(resumes.c.owner == owner)).rowcount
        s = c.execute(delete(searches).where(searches.c.owner == owner)).rowcount
    return {"analyses": a, "resumes": r, "searches": s}


# ---------- LLM call log (ROADMAP §8.2) ----------
def log_llm_call(**row) -> None:
    with engine().begin() as c:
        c.execute(insert(llm_calls).values(created_at=time.time(), **row))


def llm_spend(owner: str = "", analysis_id: str = "", since: float = 0.0) -> dict:
    from sqlalchemy import func
    q = select(func.count(), func.coalesce(func.sum(llm_calls.c.cost_usd), 0.0),
               func.coalesce(func.sum(llm_calls.c.input_tokens), 0), func.coalesce(func.sum(llm_calls.c.output_tokens), 0),
               func.coalesce(func.sum(llm_calls.c.cached_tokens), 0), func.coalesce(func.sum(llm_calls.c.cache_hit), 0),
               func.sum(func.coalesce(llm_calls.c.cost_usd, -1e9)))
    if owner:
        q = q.where(llm_calls.c.owner == owner)
    if analysis_id:
        q = q.where(llm_calls.c.analysis_id == analysis_id)
    if since:
        q = q.where(llm_calls.c.created_at >= since)
    with engine().connect() as c:
        n, cost, inp, out, cached, hits, raw = c.execute(q).one()
    return {"calls": n, "cost_usd": round(cost or 0.0, 6), "input_tokens": inp, "output_tokens": out,
            "cached_tokens": cached, "result_cache_hits": hits, "cost_known": raw is None or raw >= 0}

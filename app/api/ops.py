"""Operations endpoints: Prometheus metrics, source health (canaries), LLM spend."""
from __future__ import annotations

import os
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select

from ..runtime import metrics
from ..runtime.scheduler import CANARY_SOURCES
from ..storage import db

router = APIRouter()


def _check(request: Request) -> None:
    tok = os.getenv("METRICS_TOKEN", "")
    if tok and request.headers.get("authorization", "") != f"Bearer {tok}":
        raise HTTPException(401, "Metrics need the METRICS_TOKEN bearer token.")


@router.get("/metrics", include_in_schema=False)
async def prometheus(request: Request):
    _check(request)

    def gauges():
        with db.engine().connect() as c:
            llm = c.execute(select(db.llm_calls.c.agent, func.count(), func.coalesce(func.sum(db.llm_calls.c.cost_usd), 0.0),
                                   func.coalesce(func.sum(db.llm_calls.c.input_tokens), 0),
                                   func.coalesce(func.sum(db.llm_calls.c.cached_tokens), 0))
                            .where(db.llm_calls.c.created_at > time.time() - 86400).group_by(db.llm_calls.c.agent)).all()
            jobs = c.execute(select(func.count()).select_from(db.jobs)).scalar() or 0
            users = c.execute(select(func.count()).select_from(db.users)).scalar() or 0
            watches = c.execute(select(func.count()).select_from(db.watches).where(db.watches.c.active == 1)).scalar() or 0
        canary = [({"source": s}, 1.0 if (db.kv_get(f"canary:{s}") or {}).get("ok") else 0.0) for s in CANARY_SOURCES
                  if db.kv_get(f"canary:{s}") is not None]
        return {"llm_calls_24h": [({"agent": a}, n) for a, n, *_ in llm],
                "llm_cost_usd_24h": [({"agent": a}, cost) for a, _, cost, *_ in llm],
                "llm_cache_ratio_24h": [({"agent": a}, (cached / (inp + cached)) if (inp + cached) else 0.0) for a, _, _, inp, cached in llm],
                "jobs_stored": [({}, jobs)], "users": [({}, users)], "watches_active": [({}, watches)],
                "source_canary_up": canary}
    return PlainTextResponse(metrics.render(await run_in_threadpool(gauges)), media_type="text/plain; version=0.0.4")


@router.get("/api/admin/sources-health")
async def sources_health(request: Request):
    _check(request)
    return {s: db.kv_get(f"canary:{s}") for s in CANARY_SOURCES}

"""In-process scheduler (ROADMAP §3.5/§11): due watches every minute, source canaries hourly. One process is enough
for a single-VM deployment; run a dedicated `python -m app.runtime.scheduler` process when scaling the API out
(set SCHEDULER=off on the API replicas)."""
from __future__ import annotations

import asyncio
import logging
import os
import time

import httpx

from ..sources import BY_ID, JobQuery
from ..storage import db
from . import metrics

log = logging.getLogger("cvmatch.scheduler")
CANARY_SOURCES = ["remotive", "remoteok", "arbeitnow", "jobicy", "himalayas", "themuse", "linkedin"]


async def canaries(client: httpx.AsyncClient | None = None) -> dict:
    """Tiny search per keyless source; alerts (logs + metrics) when a parser returns 0 jobs or errors."""
    from ..sources.base import SourceError
    out = {}
    own = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(25, connect=10), follow_redirects=True)
    try:
        for sid in CANARY_SOURCES:
            src = BY_ID.get(sid)
            if not src:
                continue
            t0 = time.perf_counter()
            try:
                jobs = await asyncio.wait_for(src.fetch(JobQuery(title="engineer", count=5, hours=24 * 30), client), 60)
                ok, err, n = bool(jobs), "" if jobs else "returned 0 jobs (parser or schema drift?)", len(jobs)
            except (SourceError, asyncio.TimeoutError, Exception) as e:     # a canary must never crash the scheduler
                ok, err, n = False, str(e)[:300] or type(e).__name__, 0
            res = {"ok": ok, "jobs": n, "error": err, "ms": round((time.perf_counter() - t0) * 1000), "at": time.time()}
            out[sid] = res
            db.kv_set(f"canary:{sid}", res, 7 * 86400)
            metrics.inc("source_canary_total", source=sid, outcome="ok" if ok else "fail")
            if not ok:
                log.warning("source canary failed: %s: %s", sid, err)
    finally:
        if own:
            await client.aclose()
    return out


async def loop(stop: asyncio.Event) -> None:
    from ..api import watches
    last_canary = 0.0
    every = float(os.getenv("CANARY_INTERVAL_SECONDS", "3600"))
    while not stop.is_set():
        try:
            n = await watches.run_due()
            if n:
                metrics.inc("watch_runs_total", n, outcome="ok")
            if every > 0 and time.time() - last_canary >= every:
                last_canary = time.time()
                await canaries()
        except Exception:
            log.exception("scheduler tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=float(os.getenv("SCHEDULER_TICK_SECONDS", "60")))
        except asyncio.TimeoutError:
            pass


if __name__ == "__main__":       # dedicated scheduler process
    from .logs import setup
    setup()
    asyncio.run(loop(asyncio.Event()))

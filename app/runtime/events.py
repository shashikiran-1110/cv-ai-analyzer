"""Runs and their event streams (ROADMAP §3.5). In-process now; the interface maps onto Redis pub/sub later.

Every long operation (search, AI insights, bulk deep checks) is a run with an id. Clients read
GET /api/runs/{id}/events (SSE); events are buffered so a client that connects late (or reconnects with
Last-Event-ID) replays what it missed.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

MAX_RUNS = 500
MAX_EVENTS = 2000


@dataclass
class Run:
    id: str
    kind: str
    status: str = "running"
    created: float = field(default_factory=time.time)
    events: list[dict] = field(default_factory=list)
    cond: asyncio.Condition = field(default_factory=asyncio.Condition)


class EventBus:
    def __init__(self) -> None:
        self.runs: dict[str, Run] = {}

    def create(self, run_id: str, kind: str) -> Run:
        if len(self.runs) >= MAX_RUNS:
            for rid in sorted(self.runs, key=lambda r: self.runs[r].created)[: len(self.runs) - MAX_RUNS + 1]:
                self.runs.pop(rid, None)
        run = Run(run_id, kind)
        self.runs[run_id] = run
        return run

    def get(self, run_id: str) -> Optional[Run]:
        return self.runs.get(run_id)

    async def publish(self, run_id: str, type_: str, data: Optional[dict] = None) -> None:
        run = self.runs.get(run_id)
        if not run:
            return
        async with run.cond:
            if len(run.events) < MAX_EVENTS:
                run.events.append({"seq": len(run.events) + 1, "type": type_, "data": data or {}, "ts": time.time()})
            if type_ == "run.finished":
                run.status = (data or {}).get("status", "done")
            run.cond.notify_all()

    async def finish(self, run_id: str, status: str = "done", **extra) -> None:
        await self.publish(run_id, "run.finished", {"status": status, **extra})

    async def subscribe(self, run_id: str, after: int = 0, timeout: float = 15.0) -> AsyncIterator[dict]:
        """Yield events after `after`; yields {"type": "ping"} every `timeout` s of silence; ends after run.finished."""
        run = self.runs.get(run_id)
        if not run:
            return
        seq = after
        while True:
            async with run.cond:
                if len(run.events) <= seq and run.status == "running":
                    try:
                        await asyncio.wait_for(run.cond.wait(), timeout)
                    except asyncio.TimeoutError:
                        pass
                new = run.events[seq:]
            if not new:
                if run.status != "running":
                    return
                yield {"type": "ping", "seq": seq, "data": {}}
                continue
            for e in new:
                seq = e["seq"]
                yield e
                if e["type"] == "run.finished":
                    return


bus = EventBus()

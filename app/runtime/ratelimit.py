"""Per-client token buckets (ROADMAP §10.1). In-process; swap for a Redis bucket when running several replicas."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request


@dataclass
class Bucket:
    tokens: float
    updated: float


_buckets: dict[tuple[str, str], Bucket] = {}


def _limit(name: str) -> float:
    defaults = {"search": "30", "ai": "120", "upload": "60", "auth": "10", "ext": "600"}
    return float(os.getenv(f"RATE_LIMIT_{name.upper()}_PER_HOUR", defaults.get(name, "60")))


def client_key(request: Request) -> str:
    # behind a trusted proxy set TRUST_FORWARDED=true so X-Forwarded-For is used
    if os.getenv("TRUST_FORWARDED", "false").lower() == "true":
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check(request: Request, name: str, cost: float = 1.0) -> None:
    """Raise 429 if this client exhausted its hourly budget for `name`."""
    cap = _limit(name)
    if cap <= 0:
        return
    key = (client_key(request), name)
    now = time.monotonic()
    b = _buckets.get(key) or Bucket(cap, now)
    b.tokens = min(cap, b.tokens + (now - b.updated) * cap / 3600)
    b.updated = now
    if b.tokens < cost:
        wait = int((cost - b.tokens) * 3600 / cap) + 1
        _buckets[key] = b
        raise HTTPException(429, f"Too many {name} requests. Try again in about {max(1, wait // 60)} minute(s).",
                            headers={"Retry-After": str(wait)})
    b.tokens -= cost
    _buckets[key] = b


def reset() -> None:
    _buckets.clear()

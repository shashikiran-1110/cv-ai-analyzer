"""Source plugin interface + shared HTTP helper."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

import httpx

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")


@dataclass
class JobQuery:
    title: str
    location: str = ""
    count: int = 25
    hours: Optional[int] = None
    experience: list[str] = field(default_factory=list)
    job_types: list[str] = field(default_factory=list)
    workplace: list[str] = field(default_factory=list)
    sort: str = "recent"
    companies: dict[str, list[str]] = field(default_factory=dict)   # {"greenhouse": [...], "lever": [...], "ashby": [...]}
    urls: list[str] = field(default_factory=list)
    adzuna: Optional[dict] = None                                    # {"app_id", "app_key", "country"}
    strict: bool = True                                              # require the job title to match the query


class SourceError(Exception):
    """User-presentable failure of one source. kind: network | rate_limit | blocked | auth | http | config."""

    def __init__(self, message: str, kind: str = "http"):
        super().__init__(message)
        self.kind = kind


Progress = Callable[[int, int], Awaitable[None]]


@dataclass
class Source:
    id: str
    name: str
    kind: str                      # "search" (keyword), "board" (browse + local filter), "company", "url"
    host: str                      # for diagnostics
    fetch: Callable[..., Awaitable[list]]
    remote_only: bool = False
    needs: str = ""                # "", "companies", "urls", "adzuna_key"
    note: str = ""
    timeout: float = 60.0

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "kind": self.kind, "remote_only": self.remote_only,
                "needs": self.needs, "note": self.note, "host": self.host}


FEED_CACHE: dict[str, tuple[float, Any]] = {}
FEED_TTL = 900.0   # board feeds are identical for every user: fetch at most once per 15 minutes (ROADMAP §4.3)


async def get(client: httpx.AsyncClient, url: str, params: Optional[dict] = None, *, name: str,
              retries: int = 3, headers: Optional[dict] = None, as_json: bool = True, cache: bool = False) -> Any:
    """GET with backoff; maps failures to SourceError with a message naming the host and the fix.

    cache=True: shared feed (same response for everyone) — served from FEED_CACHE for FEED_TTL seconds."""
    key = url + "?" + "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
    if cache and key in FEED_CACHE and time.monotonic() - FEED_CACHE[key][0] < FEED_TTL:
        return FEED_CACHE[key][1]
    data = await _get_uncached(client, url, params, name=name, retries=retries, headers=headers, as_json=as_json)
    if cache:
        FEED_CACHE[key] = (time.monotonic(), data)
    return data


async def _get_uncached(client: httpx.AsyncClient, url: str, params: Optional[dict] = None, *, name: str,
                        retries: int = 3, headers: Optional[dict] = None, as_json: bool = True) -> Any:
    host = httpx.URL(url).host
    delay = 1.0
    last = ""
    for attempt in range(retries):
        try:
            r = await client.get(url, params=params, headers=headers)
        except (httpx.ProxyError, httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise SourceError(f"Can't connect to {host} ({type(e).__name__}). A firewall, proxy or sandbox "
                              f"network policy is blocking it; allow {host} or run the app on your own computer.",
                              "network")
        except httpx.HTTPError as e:
            last = type(e).__name__
        else:
            if r.status_code == 200:
                if not as_json:
                    return r.text
                try:
                    return r.json()
                except ValueError:
                    raise SourceError(f"{name} returned an unexpected (non-JSON) response; it may be blocking "
                                      "automated access right now.", "blocked")
            if r.status_code == 404:
                raise SourceError(f"{name}: not found (HTTP 404). Check the company slug or URL.", "http")
            if r.status_code in (401, 403):
                raise SourceError(f"{name} refused access (HTTP {r.status_code}). It may require a valid key or "
                                  "block automated requests from this network.", "auth" if r.status_code == 401 else "blocked")
            last = f"HTTP {r.status_code}"
            if r.status_code == 429 and r.headers.get("retry-after", "").isdigit():
                delay = min(float(r.headers["retry-after"]), 15)
            if r.status_code not in (429, 500, 502, 503, 504):
                break
        if attempt < retries - 1:
            await asyncio.sleep(delay)
            delay *= 2
    if last == "HTTP 429":
        raise SourceError(f"{name} is rate-limiting requests. Try again in a few minutes.", "rate_limit")
    raise SourceError(f"{name} failed ({last or 'unknown error'}).", "http")

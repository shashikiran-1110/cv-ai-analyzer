"""Company resolver (ROADMAP §4.2): company name → which ATS hosts its jobs, and the board slug.

Probes the public board endpoints of Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee and Personio
with a few slug candidates in parallel; a board counts only if the live probe succeeds. Results are cached in the
`companies` table (7 days). A small curated seed list answers well-known names instantly.
"""
from __future__ import annotations

import asyncio
import re
import time
import unicodedata

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import delete, insert, select

from ..runtime import ratelimit
from ..storage import db

router = APIRouter()
CACHE_DAYS = 7
SLUG_OK = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")

# (kind, url template, jobs-count extractor)
PROBES = [
    ("greenhouse", "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", lambda d: len(d.get("jobs") or [])),
    ("lever", "https://api.lever.co/v0/postings/{slug}?mode=json&limit=200", lambda d: len(d) if isinstance(d, list) else -1),
    ("ashby", "https://api.ashbyhq.com/posting-api/job-board/{slug}", lambda d: len(d.get("jobs") or [])),
    ("smartrecruiters", "https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=1", lambda d: int(d.get("totalFound") or 0)),
    ("workable", "https://apply.workable.com/api/v1/widget/accounts/{slug}", lambda d: len(d.get("jobs") or [])),
    ("recruitee", "https://{slug}.recruitee.com/api/offers/", lambda d: len(d.get("offers") or [])),
]
SEED = {   # a few widely used public boards; "Check again" re-probes them live
    "stripe": [("greenhouse", "stripe")], "airbnb": [("greenhouse", "airbnb")], "figma": [("greenhouse", "figma")],
    "databricks": [("greenhouse", "databricks")], "openai": [("ashby", "openai")],
}


def norm(name: str) -> str:
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    n = re.sub(r"\b(inc|llc|ltd|limited|gmbh|corp|corporation|co|plc|sa|ag|bv|the)\b\.?", " ", n)
    return re.sub(r"[^a-z0-9]+", " ", n).strip()


def candidates(name: str) -> list[str]:
    n = norm(name)
    if not n:
        return []
    parts = n.split()
    out = ["".join(parts), "-".join(parts), parts[0]]
    if len(parts) > 1:
        out.append("".join(parts) + "inc")
    out += [c + "hq" for c in out[:1]]
    return [c for c in dict.fromkeys(out) if SLUG_OK.match(c)][:5]


async def probe(client: httpx.AsyncClient, kind: str, url: str, count_fn, slug: str) -> dict | None:
    try:
        r = await client.get(url.format(slug=slug))
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    try:
        n = count_fn(r.json())
    except (ValueError, TypeError, AttributeError):
        return None
    return {"kind": kind, "slug": slug, "jobs": n} if n >= 0 else None


async def resolve(name: str, client: httpx.AsyncClient | None = None) -> list[dict]:
    own = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(8, connect=5), follow_redirects=False,
                                         headers={"User-Agent": "cv-match-analyzer/1.0 (company resolver)"})
    try:
        tasks = [probe(client, k, u, f, s) for s in candidates(name) for k, u, f in PROBES]
        found = [x for x in await asyncio.gather(*tasks) if x]
    finally:
        if own:
            await client.aclose()
    best: dict[str, dict] = {}
    for f in found:           # one slug per ATS: the one with the most jobs
        if f["kind"] not in best or f["jobs"] > best[f["kind"]]["jobs"]:
            best[f["kind"]] = f
    return sorted(best.values(), key=lambda f: -f["jobs"])


class ResolveIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    refresh: bool = False


@router.post("/api/companies/resolve")
async def resolve_company(body: ResolveIn, request: Request):
    key = norm(body.name)
    if not key:
        raise HTTPException(422, "Enter a company name.")

    def cached():
        with db.engine().connect() as c:
            r = c.execute(select(db.companies).where(db.companies.c.name_norm == key)).mappings().first()
        return r if r and r["checked_at"] > time.time() - CACHE_DAYS * 86400 else None
    hit = None if body.refresh else await run_in_threadpool(cached)
    if hit:
        return {"name": hit["name"], "boards": db.loads(hit["boards"], []), "cached": True}
    if not body.refresh and key in SEED:
        return {"name": body.name.strip(), "boards": [{"kind": k, "slug": s, "jobs": None} for k, s in SEED[key]], "cached": True,
                "note": "From the built-in list; job counts appear after the first search."}
    ratelimit.check(request, "search")
    boards = await resolve(body.name)

    def store():
        with db.engine().begin() as c:
            c.execute(delete(db.companies).where(db.companies.c.name_norm == key))
            c.execute(insert(db.companies).values(name_norm=key, name=body.name.strip()[:200], boards=db.dumps(boards),
                                                  checked_at=time.time()))
    await run_in_threadpool(store)
    return {"name": body.name.strip(), "boards": boards, "cached": False,
            "note": "" if boards else "No public job board found on the supported ATS platforms. Try the exact company "
                                      "name, or paste the careers page URL under Job URLs."}

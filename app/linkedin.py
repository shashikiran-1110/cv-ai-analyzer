"""Fetch public job postings from LinkedIn's unauthenticated "guest" endpoints.

These are the same HTML fragments LinkedIn's public job search page loads. No
login is used. LinkedIn can change the markup or rate-limit at any time, so the
parsers are defensive and every network call retries with backoff.
"""
from __future__ import annotations

import asyncio
import math
import re
from typing import Awaitable, Callable, Optional

import httpx
from bs4 import BeautifulSoup

from . import config
from .jobmodel import Job
from .textutil import html_to_text

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
PAGE_SIZE = 10
PAGE_DELAY = 0.4
# UI value -> LinkedIn filter code
EXPERIENCE = {"internship": "1", "entry": "2", "associate": "3", "mid_senior": "4", "director": "5", "executive": "6"}
JOB_TYPES = {"full_time": "F", "part_time": "P", "contract": "C", "temporary": "T", "internship": "I", "other": "O"}
WORKPLACE = {"on_site": "1", "remote": "2", "hybrid": "3"}
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml",
    "Referer": "https://www.linkedin.com/jobs/search",
}


def _is_authwall(r: httpx.Response) -> bool:
    url = str(r.url)
    if "authwall" in url or "/login" in url or "/checkpoint" in url:
        return True
    head = r.text[:4000].lower()
    return "session_key" in head and "base-card" not in head


class LinkedInError(Exception):
    """User-presentable failure while talking to LinkedIn. `kind`: network | rate_limit | blocked | http."""

    def __init__(self, message: str, kind: str = "http"):
        super().__init__(message)
        self.kind = kind


NETWORK_HELP = (
    "Can't connect to linkedin.com from the server ({why}). A firewall, proxy or sandbox network policy is "
    "blocking it. Allow www.linkedin.com, run the app on your own computer, or use “Paste jobs” instead."
)


ProgressCb = Callable[[str, int, int], Awaitable[None]]


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)) if node else ""


def parse_search_page(html: str) -> list[Job]:
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[Job] = []
    for card in soup.select("li, div.base-card"):
        urn = card.get("data-entity-urn") or ""
        inner = card.select_one("[data-entity-urn]") if not urn else None
        if inner is not None:
            urn = inner.get("data-entity-urn", "")
        m = re.search(r"jobPosting:(\d+)", urn)
        link = card.select_one("a.base-card__full-link, a[href*='/jobs/view/']")
        if not m and link:
            m = re.search(r"-(\d{6,})(?:\?|$)", link.get("href", "").split("?")[0] + "?")
        title = _text(card.select_one(".base-search-card__title, h3"))
        if not m or not title:
            continue
        time_el = card.select_one("time")
        href = (link.get("href", "") if link else "").split("?")[0]
        jobs.append(
            Job(
                id=m.group(1),
                title=title,
                company=_text(card.select_one(".base-search-card__subtitle, h4")),
                location=_text(card.select_one(".job-search-card__location")),
                url=href or f"https://www.linkedin.com/jobs/view/{m.group(1)}",
                posted=(time_el.get("datetime") or _text(time_el)) if time_el else "",
            )
        )
    # a card can match both the <li> and the inner div; keep first per id
    seen: set[str] = set()
    unique = []
    for j in jobs:
        if j.id not in seen:
            seen.add(j.id)
            unique.append(j)
    return unique


def parse_detail(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    desc_el = soup.select_one(".show-more-less-html__markup, .description__text")
    description = html_to_text(desc_el.decode_contents()) if desc_el else ""
    criteria: dict[str, str] = {}
    for item in soup.select("li.description__job-criteria-item"):
        key = _text(item.select_one(".description__job-criteria-subheader")).lower()
        val = _text(item.select_one(".description__job-criteria-text"))
        if key:
            criteria[key] = val
    return {
        "description": description,
        "seniority": criteria.get("seniority level", ""),
        "employment_type": criteria.get("employment type", ""),
        "extra": {k: v for k, v in criteria.items() if k in ("job function", "industries")},
    }


async def _get(client: httpx.AsyncClient, url: str, params: Optional[dict] = None,
               retries: int = 4) -> Optional[str]:
    """GET with exponential backoff. Returns None on 404, raises LinkedInError on persistent failure."""
    delay = 1.5
    last, kind = "unknown error", "http"
    for attempt in range(retries):
        try:
            r = await client.get(url, params=params)
        except (httpx.ProxyError, httpx.ConnectError, httpx.ConnectTimeout) as e:
            # connection-level failures don't get better by retrying quickly
            raise LinkedInError(NETWORK_HELP.format(why=type(e).__name__), "network")
        except httpx.HTTPError as e:
            last, kind = f"network error ({type(e).__name__})", "network"
        else:
            if r.status_code == 200:
                if _is_authwall(r):
                    raise LinkedInError(
                        "LinkedIn redirected to its sign-in page, so it's blocking anonymous job search from this "
                        "network right now. Wait a while, try another network, or use “Paste jobs”.", "blocked")
                return r.text
            if r.status_code == 404:
                return None
            last = f"HTTP {r.status_code}"
            kind = "rate_limit" if r.status_code in (429, 999) else "http"
            if r.status_code == 429 and r.headers.get("retry-after", "").isdigit():
                delay = min(float(r.headers["retry-after"]), 20)
            if r.status_code not in (429, 500, 502, 503, 504, 999):
                break
        if attempt < retries - 1:
            await asyncio.sleep(delay)
            delay *= 2
    if kind == "rate_limit":
        raise LinkedInError("LinkedIn is rate-limiting requests from this network. Wait a few minutes, ask for fewer "
                            "jobs, or use “Paste jobs”.", "rate_limit")
    if kind == "network":
        raise LinkedInError(NETWORK_HELP.format(why=last), "network")
    raise LinkedInError(f"LinkedIn returned an error ({last}). Try again shortly, or use “Paste jobs”.", "http")


async def probe(client: Optional[httpx.AsyncClient] = None) -> dict:
    """One cheap search request to tell whether LinkedIn is reachable from this server."""
    own = client is None
    client = client or httpx.AsyncClient(headers=HEADERS, timeout=12, follow_redirects=True)
    try:
        html = await _get(client, SEARCH_URL, {"keywords": "software engineer", "start": 0}, retries=1)
        n = len(parse_search_page(html or ""))
        if n:
            return {"ok": True, "message": f"LinkedIn is reachable ({n} sample postings returned)."}
        return {"ok": False, "kind": "empty", "message": "LinkedIn answered but returned no postings; it may be "
                "throttling this network. Try again in a few minutes."}
    except LinkedInError as e:
        return {"ok": False, "kind": e.kind, "message": str(e)}
    finally:
        if own:
            await client.aclose()


async def search_jobs(
    title: str,
    location: str,
    count: int,
    hours: Optional[int] = None,
    on_progress: Optional[ProgressCb] = None,
    client: Optional[httpx.AsyncClient] = None,
    *,
    experience: Optional[list[str]] = None,
    job_types: Optional[list[str]] = None,
    workplace: Optional[list[str]] = None,
    sort: str = "recent",
    warnings: Optional[list[str]] = None,
    prefilter: Optional[Callable[[Job], bool]] = None,
    postfilter: Optional[Callable[[Job], bool]] = None,
) -> list[Job]:
    """Search, page through results, then fetch full descriptions.

    ROADMAP D9: LinkedIn returns plenty of loosely related cards, so we collect up to ceil(count × 2.5) cards
    (min 30, cap 250), keep those passing `prefilter` (cheap, card-level: title/location/date), and fetch details in rank
    order until `count` jobs also pass `postfilter` (needs the description/criteria) or candidates run out."""
    count = max(1, min(count, config.MAX_JOBS))
    # ceil(count × 2.5), floor of 3 pages so small requests survive low-relevance pages; guest search stops at start < 1000
    max_cards = min(1000, max(math.ceil(count * 2.5), 3 * PAGE_SIZE))
    keep = prefilter or (lambda j: True)
    accept = postfilter or (lambda j: True)
    own_client = client is None
    client = client or httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True)

    async def progress(stage: str, done: int, total: int):
        if on_progress:
            await on_progress(stage, done, total)

    try:
        params = {"keywords": title, "location": location, "start": 0}
        if hours:
            params["f_TPR"] = f"r{int(hours) * 3600}"
        for key, vals, table in (("f_E", experience, EXPERIENCE), ("f_JT", job_types, JOB_TYPES),
                                 ("f_WT", workplace, WORKPLACE)):
            codes = [table[v] for v in (vals or []) if v in table]
            if codes:
                params[key] = ",".join(codes)
        params["sortBy"] = "R" if sort == "relevant" else "DD"
        jobs: dict[str, Job] = {}
        kept: list[Job] = []
        start, empty_pages = 0, 0
        while len(kept) < count and len(jobs) < max_cards and start < 1000 and empty_pages < 2:
            await progress("searching", len(kept), count)
            try:
                html = await _get(client, SEARCH_URL, {**params, "start": start})
            except LinkedInError as e:
                if not jobs:
                    raise
                if warnings is not None:  # keep what we already have instead of failing the whole search
                    warnings.append(f"Stopped at {len(jobs)} jobs: {e}")
                break
            page = parse_search_page(html) if html else []
            new = [j for j in page if j.id not in jobs]
            empty_pages = empty_pages + 1 if not new else 0
            for j in new:
                jobs[j.id] = j
                if keep(j):
                    kept.append(j)
            start += PAGE_SIZE
            await asyncio.sleep(PAGE_DELAY)
        if not kept:
            if jobs and warnings is not None:
                warnings.append(f"LinkedIn returned {len(jobs)} postings but none matched the title/location filters.")
            return []

        sem = asyncio.Semaphore(config.DETAIL_CONCURRENCY)
        done = 0
        failed = 0

        async def fetch_detail(job: Job):
            nonlocal done, failed
            async with sem:
                try:
                    html = await _get(client, DETAIL_URL.format(job_id=job.id), retries=3)
                    if html:
                        d = parse_detail(html)
                        job.description = d["description"]
                        job.seniority = d["seniority"]
                        job.employment_type = d["employment_type"]
                        job.extra = d["extra"]
                except LinkedInError:
                    failed += 1  # keep the job; it is flagged description_missing
                done += 1
                await progress("details", done, max(done, count))
                await asyncio.sleep(0.2)

        selected: list[Job] = []
        queue = list(kept)
        while queue and len(selected) < count:          # fetch only as many details as still needed
            batch, queue = queue[: count - len(selected)], queue[count - len(selected):]
            await progress("details", done, done + len(batch))
            await asyncio.gather(*(fetch_detail(j) for j in batch))
            selected += [j for j in batch if accept(j)]
        if failed and warnings is not None:
            warnings.append(f"{failed} of {done} job descriptions couldn't be loaded (LinkedIn throttling); "
                            "those jobs are scored from their titles only.")
        return selected[:count]
    finally:
        if own_client:
            await client.aclose()

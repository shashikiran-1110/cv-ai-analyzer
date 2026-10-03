"""Fetch public job postings from LinkedIn's unauthenticated "guest" endpoints.

These are the same HTML fragments LinkedIn's public job search page loads. No
login is used. LinkedIn can change the markup or rate-limit at any time, so the
parsers are defensive and every network call retries with backoff.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, asdict, field
from typing import Awaitable, Callable, Optional

import httpx
from bs4 import BeautifulSoup

from . import config

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
PAGE_SIZE = 10
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml",
}


class LinkedInError(Exception):
    """User-presentable failure while talking to LinkedIn."""


@dataclass
class Job:
    id: str
    title: str
    company: str = ""
    location: str = ""
    url: str = ""
    posted: str = ""
    description: str = ""
    seniority: str = ""
    employment_type: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["description_missing"] = len(self.description) < 80
        return d


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
    description = ""
    if desc_el:
        for br in desc_el.find_all("br"):
            br.replace_with("\n")
        for li in desc_el.find_all("li"):
            li.insert_before("\n• ")
        for blk in desc_el.find_all(["p", "div", "ul", "h1", "h2", "h3", "h4", "strong"]):
            blk.insert_after("\n")
        description = re.sub(r"\n\s*\n+", "\n", desc_el.get_text()).strip()
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
    """GET with exponential backoff. Returns None on 404, raises on persistent failure."""
    delay = 1.5
    last = "unknown error"
    for attempt in range(retries):
        try:
            r = await client.get(url, params=params)
        except httpx.HTTPError as e:
            last = f"network error ({type(e).__name__})"
        else:
            if r.status_code == 200:
                return r.text
            if r.status_code == 404:
                return None
            last = f"HTTP {r.status_code}"
            if r.status_code not in (429, 500, 502, 503, 504, 999):
                break
        if attempt < retries - 1:
            await asyncio.sleep(delay)
            delay *= 2
    if "429" in last or "999" in last:
        raise LinkedInError("LinkedIn is rate-limiting requests right now. Wait a few minutes or ask for fewer jobs.")
    raise LinkedInError(f"Could not reach LinkedIn ({last}).")


async def search_jobs(
    title: str,
    location: str,
    count: int,
    hours: Optional[int] = None,
    on_progress: Optional[ProgressCb] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> list[Job]:
    """Search, page through results, then fetch each job's full description."""
    count = max(1, min(count, config.MAX_JOBS))
    own_client = client is None
    client = client or httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True)

    async def progress(stage: str, done: int, total: int):
        if on_progress:
            await on_progress(stage, done, total)

    try:
        params = {"keywords": title, "location": location, "start": 0}
        if hours:
            params["f_TPR"] = f"r{int(hours) * 3600}"
        jobs: dict[str, Job] = {}
        start, empty_pages = 0, 0
        while len(jobs) < count and start < 1000 and empty_pages < 2:
            await progress("searching", len(jobs), count)
            html = await _get(client, SEARCH_URL, {**params, "start": start})
            page = parse_search_page(html) if html else []
            new = [j for j in page if j.id not in jobs]
            empty_pages = empty_pages + 1 if not new else 0
            for j in new:
                jobs[j.id] = j
            start += PAGE_SIZE
            await asyncio.sleep(0.4)
        selected = list(jobs.values())[:count]
        if not selected:
            return []

        sem = asyncio.Semaphore(config.DETAIL_CONCURRENCY)
        done = 0

        async def fetch_detail(job: Job):
            nonlocal done
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
                    pass  # keep the job; it is flagged description_missing
                done += 1
                await progress("details", done, len(selected))
                await asyncio.sleep(0.2)

        await progress("details", 0, len(selected))
        await asyncio.gather(*(fetch_detail(j) for j in selected))
        return selected
    finally:
        if own_client:
            await client.aclose()

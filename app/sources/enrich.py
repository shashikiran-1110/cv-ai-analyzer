"""Detail enrichment for selected jobs (fixes "missing details").

Aggregators and boards often return short or truncated descriptions and no salary. For each selected job that is
thin (description < 400 chars, Adzuna's truncated text, or no salary), fetch the posting's own page through the SSRF
guard and read its schema.org JobPosting data. Hosts that block bots (Wellfound, Indeed, Glassdoor) and LinkedIn
(handled by its own detail endpoint) are skipped. Salary is also parsed from description text when still missing.
"""
from __future__ import annotations

import asyncio
import re
from typing import Awaitable, Callable, Optional
from urllib.parse import urlparse

import httpx

from ..jobmodel import Job
from ..net.safe_fetch import UnsafeURL, safe_get
from .base import UA
from .urlimport import _BLOCKY, parse_job_page

THIN = 400
SKIP_HOSTS = tuple(_BLOCKY) + ("linkedin.com",)
_CUR = r"(?:[$£€₹]|USD|GBP|EUR|INR|CAD|AUD)"
_NUM = r"\d{1,3}(?:[,.\s]\d{2,3})*(?:\.\d+)?\s*(?:[kK]|LPA|lpa|lakhs?)?"   # 2-digit groups: Indian lakh format
_PERIOD = r"(?:per|a|an|/)\s*(?:year|annum|yr|hour|hr|month|mo|day)|annually|hourly|p\.?a\.?"
SALARY = re.compile(rf"({_CUR}\s?{_NUM}(?:\s*(?:-|–|to)\s*{_CUR}?\s?{_NUM})?(?:\s*(?:{_PERIOD}))?)", re.I)


def salary_from_text(text: str) -> str:
    """First salary-looking amount with a currency: '£45,000–55,000 a year', '$60/hr', '€70k - €85k'."""
    for m in SALARY.finditer(text or ""):
        s = re.sub(r"\s+", " ", m.group(1)).strip(" -–")
        digits = re.sub(r"\D", "", s.split("-")[0].split("–")[0])
        if len(digits) >= 2 and not re.fullmatch(rf"{_CUR}\s?\d{{1,2}}", s):     # skip "$5" style noise
            return s[:60]
    return ""


def needs_enrichment(j: Job) -> bool:
    return len(j.description or "") < THIN or bool((j.extra or {}).get("truncated")) or not j.salary


def _fetchable(url: str) -> bool:
    u = urlparse(url or "")
    host = (u.hostname or "").lower()
    return u.scheme in ("http", "https") and bool(host) and not any(host.endswith(h) for h in SKIP_HOSTS)


async def enrich(jobs: list[Job], client: httpx.AsyncClient, on_progress: Optional[Callable[[int, int], Awaitable[None]]] = None,
                 concurrency: int = 8, timeout: float = 10.0, max_fetch: int = 200) -> int:
    """Enrich thin jobs in place. Returns how many gained a better description or a salary."""
    for j in jobs:                                    # free win first: salary stated in the text we already have
        if not j.salary:
            j.salary = salary_from_text(j.description)
    todo = [j for j in jobs if needs_enrichment(j) and _fetchable(j.url) and (len(j.description or "") < THIN or (j.extra or {}).get("truncated"))]
    todo = todo[:max_fetch]                           # selected jobs are already in rank order
    if not todo:
        return 0
    sem = asyncio.Semaphore(concurrency)
    done = improved = 0

    async def one(j: Job) -> None:
        nonlocal done, improved
        async with sem:
            try:
                page = await asyncio.wait_for(safe_get(client, j.url, headers={"User-Agent": UA, "Accept": "text/html"}), timeout)
                got = parse_job_page(page.text, j.url) if page.status == 200 else None
            except (UnsafeURL, httpx.HTTPError, asyncio.TimeoutError, ValueError):
                got = None
            if got and not (got.extra or {}).get("unstructured"):
                better = False
                if len(got.description) > len(j.description) + 100:
                    j.description, better = got.description, True
                    j.extra.pop("truncated", None)
                if not j.salary and got.salary:
                    j.salary, better = got.salary, True
                if not j.employment_type and got.employment_type:
                    j.employment_type = got.employment_type
                if better:
                    j.extra["enriched"] = True
                    improved += 1
            if not j.salary:
                j.salary = salary_from_text(j.description)
            done += 1
            if on_progress:
                await on_progress(done, len(todo))

    await asyncio.gather(*(one(j) for j in todo))
    return improved

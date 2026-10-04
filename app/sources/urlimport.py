"""Import individual job URLs (Wellfound, company career pages, Greenhouse/Lever/Workday pages, …).

Uses the page's schema.org JobPosting JSON-LD, which publishers embed for search engines; falls back to the
page's main text. LinkedIn job URLs are routed to LinkedIn's guest job endpoint.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from .. import linkedin
from ..net.safe_fetch import UnsafeURL, safe_get
from ..jobmodel import Job
from ..textutil import html_to_text, parse_date
from .base import UA, JobQuery, Source, SourceError

_LI = re.compile(r"linkedin\.com/jobs/(?:view|collections/[^?]*currentJobId=)[^\d]*?(\d{6,})|currentJobId=(\d{6,})")
_JOB_CUES = [r"\brequirements?\b", r"\bqualifications?\b", r"\bresponsibilit", r"\bapply\b",
             r"\bexperience\b", r"\b(?:full|part)[\s-]time\b", r"\bsalary\b|\bcompensation\b", r"\bwhat you'?ll\b"]
_BLOCKY = {"wellfound.com": "Wellfound", "angel.co": "Wellfound", "indeed.com": "Indeed", "glassdoor.com": "Glassdoor"}


def _find_posting(node: Any) -> Optional[dict]:
    if isinstance(node, list):
        for x in node:
            r = _find_posting(x)
            if r:
                return r
    elif isinstance(node, dict):
        t = node.get("@type")
        if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
            return node
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in node:
                r = _find_posting(node[key])
                if r:
                    return r
    return None


def _loc(p: dict) -> str:
    locs = p.get("jobLocation") or []
    if isinstance(locs, dict):
        locs = [locs]
    names = []
    for l in locs:
        a = (l or {}).get("address") or {}
        if isinstance(a, str):
            names.append(a)
            continue
        country = a.get("addressCountry")
        if isinstance(country, dict):
            country = country.get("name")
        parts = [a.get("addressLocality"), a.get("addressRegion"), country]
        names.append(", ".join(x for x in parts if x))
    remote = p.get("jobLocationType") == "TELECOMMUTE"
    out = "; ".join(n for n in names if n)
    return (out + " (remote)" if out else "Remote") if remote else out


def parse_job_page(html: str, url: str) -> Optional[Job]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except ValueError:
            continue
        p = _find_posting(data)
        if not p:
            continue
        org = p.get("hiringOrganization") or {}
        et = p.get("employmentType") or ""
        sal = ""
        bs = p.get("baseSalary") or {}
        if isinstance(bs, dict) and isinstance(bs.get("value"), dict):
            v = bs["value"]
            sal = f"{v.get('minValue', '')}–{v.get('maxValue', '')} {bs.get('currency', '')} {v.get('unitText', '')}".strip(" –")
        return Job(
            id="url-" + hashlib.md5(url.encode()).hexdigest()[:12], title=html_to_text(str(p.get("title", ""))),
            company=org.get("name", "") if isinstance(org, dict) else str(org), location=_loc(p), url=url,
            posted=parse_date(p.get("datePosted")), description=html_to_text(p.get("description")),
            employment_type=", ".join(et) if isinstance(et, list) else str(et).replace("_", " ").lower(),
            remote=p.get("jobLocationType") == "TELECOMMUTE" or None, salary=sal, source="url")
    # Fallback: page title + main content text
    title = (soup.find("meta", property="og:title") or {}).get("content") or (soup.title.string if soup.title else "")
    main = soup.find("main") or soup.find("article") or soup.body
    text = html_to_text(main.decode_contents()) if main else ""
    cues = sum(bool(re.search(p, text, re.I)) for p in _JOB_CUES)
    if title and len(text) > 300 and cues >= 2:   # don't turn arbitrary pages into "job descriptions"
        return Job(id="url-" + hashlib.md5(url.encode()).hexdigest()[:12], title=title.strip()[:200], url=url,
                   description=text[:20000], source="url", extra={"unstructured": True})
    return None


async def import_urls(q: JobQuery, client: httpx.AsyncClient) -> list[Job]:
    urls = list(dict.fromkeys(u.strip() for u in q.urls if u.strip()))[:100]
    if not urls:
        raise SourceError("Paste at least one job URL.", "config")

    async def one(url: str) -> Job:
        pu = urlparse(url)
        if pu.scheme not in ("http", "https") or not pu.netloc:
            raise SourceError(f"Not a valid URL: {url[:80]}", "config")
        m = _LI.search(url) if (pu.hostname or "").lower().endswith("linkedin.com") else None
        if m:
            jid = m.group(1) or m.group(2)
            html = await linkedin._get(client, linkedin.DETAIL_URL.format(job_id=jid), retries=2)
            d = linkedin.parse_detail(html or "")
            soup = BeautifulSoup(html or "", "html.parser")
            t = soup.select_one(".top-card-layout__title, h2")
            c = soup.select_one(".topcard__org-name-link, .top-card-layout__card a")
            return Job(id=jid, title=t.get_text(strip=True) if t else "LinkedIn job", company=c.get_text(strip=True) if c else "",
                       url=f"https://www.linkedin.com/jobs/view/{jid}", description=d["description"],
                       seniority=d["seniority"], employment_type=d["employment_type"], source="linkedin")
        host = (pu.hostname or "").lower().removeprefix("www.")
        brand = next((v for k, v in _BLOCKY.items() if host.endswith(k)), None)
        try:
            page = await safe_get(client, url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"})
        except UnsafeURL as e:
            raise SourceError(f"{url[:80]}: {e}", "config")
        except (httpx.ProxyError, httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise SourceError(f"Can't connect to {host} ({type(e).__name__}).", "network")
        except httpx.HTTPError as e:
            raise SourceError(f"{host}: network error ({type(e).__name__}).", "http")
        if page.status != 200:
            if brand:
                raise SourceError(f"{brand} blocked the request for {url[:80]} (it blocks automated access). "
                                  "Open the job in your browser and use “Paste jobs” instead.", "blocked")
            raise SourceError(f"{host} returned HTTP {page.status} for {url[:80]}.", "http")
        html = page.text
        job = parse_job_page(html, url)
        if not job:
            raise SourceError(f"Couldn't find a job posting on {url[:80]}"
                              + (f" ({brand} may have served a bot check)." if brand else "."), "http")
        return job

    sem = asyncio.Semaphore(8)

    async def bounded(u: str) -> Job:
        async with sem:
            return await one(u)
    results = await asyncio.gather(*(bounded(u) for u in urls), return_exceptions=True)
    for u, r in zip(urls, results):           # per-link outcome (shown in the saved-links list)
        q.url_results[u] = ({"ok": True, "title": r.title, "company": r.company, "message": ""} if isinstance(r, Job)
                            else {"ok": False, "title": "", "company": "", "message": str(r)[:300]})
    jobs = [r for r in results if isinstance(r, Job)]
    errors = [str(r) for r in results if isinstance(r, Exception)]
    if errors and not jobs:
        raise SourceError(" | ".join(errors)[:800], "http")
    if errors:
        jobs[0].extra.setdefault("_warnings", []).extend(errors)
    return jobs


SOURCES = [Source("urls", "Job URLs (Wellfound, career pages…)", "url", "", import_urls, needs="urls",
                  note="Paste links to individual postings; uses each page's structured job data")]

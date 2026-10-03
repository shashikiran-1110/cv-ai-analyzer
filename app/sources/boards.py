"""Public job-board APIs (official, unauthenticated)."""
from __future__ import annotations

import asyncio
import hashlib

import httpx

from ..jobmodel import Job
from ..textutil import html_to_text, parse_date
from .base import JobQuery, Source, get


def _s(v) -> str:
    return "" if v is None else str(v).strip()


async def remotive(q: JobQuery, client: httpx.AsyncClient) -> list[Job]:
    data = await get(client, "https://remotive.com/api/remote-jobs", {"search": q.title, "limit": 150}, name="Remotive")
    out = []
    for j in data.get("jobs", []) or []:
        out.append(Job(
            id=f"remotive-{j.get('id')}", title=_s(j.get("title")), company=_s(j.get("company_name")),
            location=_s(j.get("candidate_required_location")) or "Remote", url=_s(j.get("url")),
            posted=parse_date(j.get("publication_date")), description=html_to_text(j.get("description")),
            employment_type=_s(j.get("job_type")).replace("_", " "), remote=True, salary=_s(j.get("salary")),
            tags=list(j.get("tags") or []), source="remotive"))
    return out


async def remoteok(q: JobQuery, client: httpx.AsyncClient) -> list[Job]:
    data = await get(client, "https://remoteok.com/api", name="RemoteOK", cache=True)
    out = []
    for j in data if isinstance(data, list) else []:
        if not isinstance(j, dict) or not j.get("id") or not j.get("position"):
            continue  # first element is the API's legal notice
        sal = f"{j.get('salary_min')}–{j.get('salary_max')}" if j.get("salary_min") and j.get("salary_max") else ""
        out.append(Job(
            id=f"remoteok-{j['id']}", title=_s(j.get("position")), company=_s(j.get("company")),
            location=_s(j.get("location")) or "Remote", url=_s(j.get("url")) or f"https://remoteok.com/remote-jobs/{j['id']}",
            posted=parse_date(j.get("date") or j.get("epoch")), description=html_to_text(j.get("description")),
            remote=True, salary=sal, tags=list(j.get("tags") or []), source="remoteok"))
    return out


async def arbeitnow(q: JobQuery, client: httpx.AsyncClient) -> list[Job]:
    out = []
    for page in (1, 2, 3):
        data = await get(client, "https://www.arbeitnow.com/api/job-board-api", {"page": page}, name="Arbeitnow", cache=True)
        rows = data.get("data", []) or []
        for j in rows:
            out.append(Job(
                id=f"arbeitnow-{j.get('slug')}", title=_s(j.get("title")), company=_s(j.get("company_name")),
                location=_s(j.get("location")) or ("Remote" if j.get("remote") else ""), url=_s(j.get("url")),
                posted=parse_date(j.get("created_at")), description=html_to_text(j.get("description")),
                employment_type=", ".join(j.get("job_types") or []), remote=bool(j.get("remote")),
                tags=list(j.get("tags") or []), source="arbeitnow"))
        if not rows or not (data.get("links") or {}).get("next"):
            break
    return out


async def jobicy(q: JobQuery, client: httpx.AsyncClient) -> list[Job]:
    params = {"count": 50, "tag": q.title}
    data = await get(client, "https://jobicy.com/api/v2/remote-jobs", params, name="Jobicy")
    out = []
    for j in data.get("jobs", []) or []:
        jt = j.get("jobType") or []
        out.append(Job(
            id=f"jobicy-{j.get('id')}", title=_s(j.get("jobTitle")), company=_s(j.get("companyName")),
            location=_s(j.get("jobGeo")) or "Remote", url=_s(j.get("url")), posted=parse_date(j.get("pubDate")),
            description=html_to_text(j.get("jobDescription") or j.get("jobExcerpt")),
            employment_type=", ".join(jt) if isinstance(jt, list) else _s(jt), seniority=_s(j.get("jobLevel")),
            remote=True, source="jobicy"))
    return out


async def himalayas(q: JobQuery, client: httpx.AsyncClient) -> list[Job]:
    from .base import SourceError
    try:
        data = await get(client, "https://himalayas.app/jobs/api/search", {"q": q.title, "page": 1}, name="Himalayas")
    except SourceError as e:
        if "404" not in str(e):
            raise
        data = await get(client, "https://himalayas.app/jobs/api", {"limit": 100}, name="Himalayas", cache=True)
    out = []
    for j in data.get("jobs", []) or []:
        locs = j.get("locationRestrictions") or []
        sal = f"{j.get('minSalary')}–{j.get('maxSalary')} {j.get('currency') or ''}".strip() if j.get("minSalary") else ""
        sen = j.get("seniority") or []
        out.append(Job(
            id="himalayas-" + hashlib.md5(str(j.get('guid') or j.get('applicationLink') or j.get('title')).encode()).hexdigest()[:12],
            title=_s(j.get("title")), company=_s(j.get("companyName")),
            location=", ".join(locs) if locs else "Remote (worldwide)",
            url=_s(j.get("applicationLink") or j.get("guid")), posted=parse_date(j.get("pubDate")),
            description=html_to_text(j.get("description") or j.get("excerpt")),
            employment_type=_s(j.get("employmentType")), seniority=", ".join(sen) if isinstance(sen, list) else _s(sen),
            remote=True, salary=sal, tags=list(j.get("categories") or []), source="himalayas"))
    return out


async def themuse(q: JobQuery, client: httpx.AsyncClient) -> list[Job]:
    async def page(p: int):
        return await get(client, "https://www.themuse.com/api/public/jobs", {"page": p, "descending": "true"}, name="The Muse",
                         cache=True)

    pages = await asyncio.gather(*(page(p) for p in range(5)), return_exceptions=True)
    if all(isinstance(x, Exception) for x in pages):
        raise pages[0]  # type: ignore[misc]
    out = []
    for data in pages:
        if isinstance(data, Exception):
            continue
        for j in data.get("results", []) or []:
            locs = [l.get("name", "") for l in j.get("locations") or []]
            out.append(Job(
                id=f"themuse-{j.get('id')}", title=_s(j.get("name")), company=_s((j.get("company") or {}).get("name")),
                location=", ".join(locs), url=_s((j.get("refs") or {}).get("landing_page")),
                posted=parse_date(j.get("publication_date")), description=html_to_text(j.get("contents")),
                seniority=", ".join(l.get("name", "") for l in j.get("levels") or []),
                remote=any("remote" in l.lower() or "flexible" in l.lower() for l in locs) or None, source="themuse"))
    return out


SOURCES = [
    Source("remotive", "Remotive", "search", "remotive.com", remotive, remote_only=True, note="Curated remote jobs"),
    Source("remoteok", "RemoteOK", "board", "remoteok.com", remoteok, remote_only=True, note="Latest remote jobs"),
    Source("arbeitnow", "Arbeitnow", "board", "www.arbeitnow.com", arbeitnow, note="Europe (mostly Germany) + remote"),
    Source("jobicy", "Jobicy", "search", "jobicy.com", jobicy, remote_only=True, note="Remote jobs"),
    Source("himalayas", "Himalayas", "search", "himalayas.app", himalayas, remote_only=True, note="Remote jobs"),
    Source("themuse", "The Muse", "board", "www.themuse.com", themuse, note="US-heavy, curated companies"),
]

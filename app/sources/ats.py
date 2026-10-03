"""Company applicant-tracking-system job boards: the canonical source for those companies' postings."""
from __future__ import annotations

import asyncio
import re

import httpx

from ..jobmodel import Job
from ..textutil import html_to_text, parse_date
from .base import JobQuery, Source, SourceError, get

SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$|^[a-z0-9-]{1,60}/wd\d{1,2}/[A-Za-z0-9_-]{1,80}$")   # 2nd: Workday


def _nice(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").title()


async def _each(q: JobQuery, kind: str, fn) -> list[Job]:
    slugs = [s.strip() for s in q.companies.get(kind, []) if s.strip()]
    if not slugs:
        raise SourceError("Add at least one company slug for this source.", "config")
    bad = [s for s in slugs if not SLUG.match(s)]
    if bad:
        raise SourceError(f"Invalid company slug(s): {', '.join(bad)}", "config")
    results = await asyncio.gather(*(fn(s) for s in slugs[:30]), return_exceptions=True)
    jobs, errors = [], []
    for slug, r in zip(slugs, results):
        if isinstance(r, Exception):
            errors.append(f"{slug}: {r}")
        else:
            jobs.extend(r)
    if errors and not jobs:
        raise SourceError("; ".join(errors)[:600], "http")
    if errors:
        jobs[0].extra.setdefault("_warnings", []).extend(errors)
    return jobs


async def greenhouse(q: JobQuery, client: httpx.AsyncClient) -> list[Job]:
    async def one(slug: str) -> list[Job]:
        data = await get(client, f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", {"content": "true"},
                         name=f"Greenhouse ({slug})")
        return [Job(
            id=f"greenhouse-{slug}-{j.get('id')}", title=str(j.get("title", "")).strip(),
            company=j.get("company_name") or _nice(slug), location=(j.get("location") or {}).get("name", ""),
            url=j.get("absolute_url", ""), posted=parse_date(j.get("first_published") or j.get("updated_at")),
            description=html_to_text(j.get("content")), source="greenhouse") for j in data.get("jobs", []) or []]
    return await _each(q, "greenhouse", one)


async def lever(q: JobQuery, client: httpx.AsyncClient) -> list[Job]:
    async def one(slug: str) -> list[Job]:
        data = await get(client, f"https://api.lever.co/v0/postings/{slug}", {"mode": "json"}, name=f"Lever ({slug})")
        out = []
        for j in data if isinstance(data, list) else []:
            parts = [j.get("descriptionPlain") or html_to_text(j.get("description"))]
            for lst in j.get("lists") or []:
                parts.append(f"{lst.get('text', '')}\n{html_to_text(lst.get('content'))}")
            parts.append(j.get("additionalPlain") or "")
            cat = j.get("categories") or {}
            wt = (j.get("workplaceType") or "").lower()
            out.append(Job(
                id=f"lever-{slug}-{j.get('id')}", title=str(j.get("text", "")).strip(), company=_nice(slug),
                location=cat.get("location", ""), url=j.get("hostedUrl", ""), posted=parse_date(j.get("createdAt")),
                description="\n".join(p for p in parts if p).strip(), employment_type=cat.get("commitment", ""),
                remote=True if wt == "remote" else (False if wt in ("onsite", "on-site") else None), source="lever"))
        return out
    return await _each(q, "lever", one)


async def ashby(q: JobQuery, client: httpx.AsyncClient) -> list[Job]:
    async def one(slug: str) -> list[Job]:
        data = await get(client, f"https://api.ashbyhq.com/posting-api/job-board/{slug}", {"includeCompensation": "true"},
                         name=f"Ashby ({slug})")
        out = []
        for j in data.get("jobs", []) or []:
            comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
            out.append(Job(
                id=f"ashby-{slug}-{j.get('id')}", title=str(j.get("title", "")).strip(), company=_nice(slug),
                location=j.get("location", ""), url=j.get("jobUrl", ""), posted=parse_date(j.get("publishedAt")),
                description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml")),
                employment_type=j.get("employmentType", ""), remote=j.get("isRemote"), salary=comp, source="ashby"))
        return out
    return await _each(q, "ashby", one)


SOURCES = [
    Source("greenhouse", "Greenhouse boards", "company", "boards-api.greenhouse.io", greenhouse, needs="companies",
           note="Company slugs, e.g. stripe, airbnb (from boards.greenhouse.io/<slug>)"),
    Source("lever", "Lever boards", "company", "api.lever.co", lever, needs="companies",
           note="Company slugs from jobs.lever.co/<slug>"),
    Source("ashby", "Ashby boards", "company", "api.ashbyhq.com", ashby, needs="companies",
           note="Company slugs from jobs.ashbyhq.com/<slug>"),
]

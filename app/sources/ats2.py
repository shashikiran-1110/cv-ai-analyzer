"""More company ATS boards (ROADMAP §4.1 Tier 1) and USAJOBS (Tier 2).

All are public, read-only posting feeds that companies publish for their own career sites:
SmartRecruiters (Posting API), Workable (careers widget API), Recruitee (offers API), Personio (XML feed),
Teamtailor (career-site RSS), Workday (the career site's own `cxs` JSON). USAJOBS needs a free key + email.
Slugs: smartrecruiters `Company1`, workable `acme`, recruitee `acme`, personio `acme`, teamtailor `acme`,
workday `tenant/wd5/SiteName` (from https://tenant.wd5.myworkdayjobs.com/SiteName).
"""
from __future__ import annotations

import asyncio
import math
import re
import xml.etree.ElementTree as ET

import httpx

from ..jobmodel import Job
from ..textutil import html_to_text, parse_date
from .ats import _each, _nice
from .base import JobQuery, Source, SourceError, get, post_json

WORKDAY_SLUG = re.compile(r"^([a-z0-9-]{1,60})/(wd\d{1,2})/([A-Za-z0-9_-]{1,80})$")
DETAIL_LIMIT = 30          # detail calls per company per search (feeds without full text in the list)


async def _bounded(coros, n: int = 6):
    sem = asyncio.Semaphore(n)

    async def run(c):
        async with sem:
            return await c
    return await asyncio.gather(*(run(c) for c in coros), return_exceptions=True)


async def smartrecruiters(q: JobQuery, client: httpx.AsyncClient) -> list[Job]:
    async def one(slug: str) -> list[Job]:
        base = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
        data = await get(client, base, {"limit": 100, **({"q": q.title} if q.title else {})}, name=f"SmartRecruiters ({slug})")
        rows = data.get("content", []) or []
        details = await _bounded([get(client, f"{base}/{r.get('id')}", name=f"SmartRecruiters ({slug})") for r in rows[:DETAIL_LIMIT]])
        out = []
        for i, r in enumerate(rows):
            d = details[i] if i < len(details) and not isinstance(details[i], Exception) else {}
            secs = ((d or {}).get("jobAd") or {}).get("sections") or {}
            desc = "\n\n".join(html_to_text((secs.get(k) or {}).get("text")) for k in
                               ("jobDescription", "qualifications", "additionalInformation") if (secs.get(k) or {}).get("text"))
            loc = r.get("location") or {}
            out.append(Job(id=f"smartrecruiters-{slug}-{r.get('id')}", title=str(r.get("name", "")).strip(),
                           company=(r.get("company") or {}).get("name") or _nice(slug),
                           location=", ".join(x for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x),
                           url=f"https://jobs.smartrecruiters.com/{slug}/{r.get('id')}", posted=parse_date(r.get("releasedDate")),
                           description=desc, employment_type=(r.get("typeOfEmployment") or {}).get("label", ""),
                           remote=loc.get("remote"), source="smartrecruiters"))
        return out
    return await _each(q, "smartrecruiters", one)


async def workable(q: JobQuery, client: httpx.AsyncClient) -> list[Job]:
    async def one(slug: str) -> list[Job]:
        data = await get(client, f"https://apply.workable.com/api/v1/widget/accounts/{slug}", {"details": "true"},
                         name=f"Workable ({slug})")
        return [Job(id=f"workable-{slug}-{j.get('shortcode')}", title=str(j.get("title", "")).strip(),
                    company=data.get("name") or _nice(slug),
                    location=", ".join(x for x in (j.get("city"), j.get("state"), j.get("country")) if x),
                    url=j.get("url") or j.get("shortlink", ""), posted=parse_date(j.get("published_on") or j.get("created_at")),
                    description=html_to_text(j.get("description")), employment_type=j.get("employment_type", ""),
                    remote=True if j.get("telecommuting") else None, source="workable") for j in data.get("jobs", []) or []]
    return await _each(q, "workable", one)


async def recruitee(q: JobQuery, client: httpx.AsyncClient) -> list[Job]:
    async def one(slug: str) -> list[Job]:
        data = await get(client, f"https://{slug}.recruitee.com/api/offers/", name=f"Recruitee ({slug})")
        out = []
        for j in data.get("offers", []) or []:
            desc = "\n\n".join(html_to_text(j.get(k)) for k in ("description", "requirements") if j.get(k))
            out.append(Job(id=f"recruitee-{slug}-{j.get('id')}", title=str(j.get("title", "")).strip(),
                           company=j.get("company_name") or _nice(slug), location=j.get("location") or
                           ", ".join(x for x in (j.get("city"), j.get("country")) if x),
                           url=j.get("careers_url", ""), posted=parse_date(j.get("published_at") or j.get("created_at")),
                           description=desc, employment_type=(j.get("employment_type_code") or "").replace("_", " "),
                           remote=j.get("remote"), source="recruitee"))
        return out
    return await _each(q, "recruitee", one)


def _xml_text(el, path: str) -> str:
    x = el.find(path)
    return (x.text or "").strip() if x is not None and x.text else ""


async def personio(q: JobQuery, client: httpx.AsyncClient) -> list[Job]:
    async def one(slug: str) -> list[Job]:
        text = await get(client, f"https://{slug}.jobs.personio.de/xml", name=f"Personio ({slug})", as_json=False)
        try:
            root = ET.fromstring(text.encode())
        except ET.ParseError:
            raise SourceError(f"Personio ({slug}) returned an unreadable feed.", "http")
        out = []
        for p in root.iter("position"):
            pid = _xml_text(p, "id")
            parts = [f"{_xml_text(d, 'name')}\n{html_to_text(_xml_text(d, 'value'))}" for d in p.iter("jobDescription")]
            out.append(Job(id=f"personio-{slug}-{pid}", title=_xml_text(p, "name"), company=_xml_text(p, "subcompany") or _nice(slug),
                           location=_xml_text(p, "office"), url=f"https://{slug}.jobs.personio.de/job/{pid}",
                           posted=parse_date(_xml_text(p, "createdAt")), description="\n\n".join(parts).strip(),
                           employment_type=_xml_text(p, "schedule") or _xml_text(p, "employmentType"), source="personio"))
        return out
    return await _each(q, "personio", one)


async def teamtailor(q: JobQuery, client: httpx.AsyncClient) -> list[Job]:
    async def one(slug: str) -> list[Job]:
        text = await get(client, f"https://{slug}.teamtailor.com/jobs.rss", name=f"Teamtailor ({slug})", as_json=False)
        try:
            root = ET.fromstring(text.encode())
        except ET.ParseError:
            raise SourceError(f"Teamtailor ({slug}) returned an unreadable feed.", "http")
        out = []
        for it in root.iter("item"):
            link = _xml_text(it, "link")
            loc = next((x.text or "" for x in it.iter() if x.tag.endswith("location") or x.tag.endswith("city")), "")
            out.append(Job(id=f"teamtailor-{slug}-{(link.rstrip('/').rsplit('/', 1)[-1] or _xml_text(it, 'guid'))[:80]}",
                           title=_xml_text(it, "title"), company=_nice(slug), location=loc.strip(), url=link,
                           posted=parse_date(_xml_text(it, "pubDate")), description=html_to_text(_xml_text(it, "description")),
                           source="teamtailor"))
        return out
    return await _each(q, "teamtailor", one)


async def workday(q: JobQuery, client: httpx.AsyncClient) -> list[Job]:
    slugs = [s.strip() for s in q.companies.get("workday", []) if s.strip()]
    bad = [s for s in slugs if not WORKDAY_SLUG.match(s)]
    if bad:
        raise SourceError(f"Workday sites look like tenant/wd5/SiteName (from tenant.wd5.myworkdayjobs.com/SiteName); "
                          f"got: {', '.join(bad)}", "config")

    async def one(slug: str) -> list[Job]:
        tenant, wd, site = WORKDAY_SLUG.match(slug).groups()
        base = f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"
        data = await post_json(client, f"{base}/jobs", {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": q.title},
                               name=f"Workday ({tenant})")
        posts = data.get("jobPostings", []) or []
        details = await _bounded([get(client, f"{base}{p.get('externalPath', '')}", name=f"Workday ({tenant})") for p in posts[:DETAIL_LIMIT]])
        out = []
        for i, p in enumerate(posts):
            d = details[i] if i < len(details) and not isinstance(details[i], Exception) else {}
            info = (d or {}).get("jobPostingInfo") or {}
            out.append(Job(id=f"workday-{tenant}-{p.get('externalPath', '').rsplit('_', 1)[-1] or i}", title=str(p.get("title", "")).strip(),
                           company=_nice(tenant), location=info.get("location") or p.get("locationsText", ""),
                           url=info.get("externalUrl") or f"https://{tenant}.{wd}.myworkdayjobs.com/{site}{p.get('externalPath', '')}",
                           posted=parse_date(info.get("startDate")) or p.get("postedOn", ""),
                           description=html_to_text(info.get("jobDescription")), employment_type=info.get("timeType", ""),
                           source="workday"))
        return out
    return await _each(q, "workday", one)


async def usajobs(q: JobQuery, client: httpx.AsyncClient) -> list[Job]:
    cfg = q.usajobs or {}
    email, key = str(cfg.get("email", "")).strip(), str(cfg.get("key", "")).strip()
    if not email or not key:
        raise SourceError("USAJOBS needs your email and a free API key (developer.usajobs.gov).", "config")
    params = {"Keyword": q.title, "ResultsPerPage": min(250, max(25, q.count * 2))}
    if q.location and q.location.lower() not in ("remote", "anywhere", "usa", "us", "united states"):
        params["LocationName"] = q.location
    if q.hours:
        params["DatePosted"] = max(1, math.ceil(q.hours / 24))
    try:
        data = await get(client, "https://data.usajobs.gov/api/search", params, name="USAJOBS",
                         headers={"Host": "data.usajobs.gov", "User-Agent": email, "Authorization-Key": key})
    except SourceError as e:
        raise SourceError(str(e).replace(key, "***") if len(key) >= 6 else str(e), e.kind)
    out = []
    for item in ((data.get("SearchResult") or {}).get("SearchResultItems") or []):
        m = item.get("MatchedObjectDescriptor") or {}
        det = (m.get("UserArea") or {}).get("Details") or {}
        pay = (m.get("PositionRemuneration") or [{}])[0]
        desc = "\n\n".join(x for x in [det.get("JobSummary", ""), "\n".join(det.get("MajorDuties") or []),
                                       "Qualifications\n" + (m.get("QualificationSummary") or ""), det.get("Requirements", ""),
                                       det.get("Education", "")] if x and x.strip())
        sal = f"${pay.get('MinimumRange', '')}–{pay.get('MaximumRange', '')} {pay.get('Description', '')}".strip() if pay.get("MinimumRange") else ""
        out.append(Job(id=f"usajobs-{m.get('PositionID') or m.get('MatchedObjectId', '')}", title=m.get("PositionTitle", ""),
                       company=m.get("OrganizationName", ""), location=m.get("PositionLocationDisplay", ""),
                       url=m.get("PositionURI", ""), posted=parse_date(m.get("PublicationStartDate")), description=desc,
                       salary=sal, source="usajobs"))
    return out


SOURCES = [
    Source("smartrecruiters", "SmartRecruiters boards", "company", "api.smartrecruiters.com", smartrecruiters, needs="companies",
           note="Company identifiers from jobs.smartrecruiters.com/<Company>"),
    Source("workable", "Workable boards", "company", "apply.workable.com", workable, needs="companies",
           note="Account slugs from apply.workable.com/<slug>"),
    Source("recruitee", "Recruitee boards", "company", "recruitee.com", recruitee, needs="companies",
           note="Subdomains from <slug>.recruitee.com"),
    Source("personio", "Personio boards", "company", "jobs.personio.de", personio, needs="companies",
           note="Subdomains from <slug>.jobs.personio.de"),
    Source("teamtailor", "Teamtailor boards", "company", "teamtailor.com", teamtailor, needs="companies",
           note="Subdomains from <slug>.teamtailor.com"),
    Source("workday", "Workday career sites", "company", "myworkdayjobs.com", workday, needs="companies",
           note="tenant/wd5/SiteName from tenant.wd5.myworkdayjobs.com/SiteName", timeout=90.0),
    Source("usajobs", "USAJOBS (US federal)", "search", "data.usajobs.gov", usajobs, needs="usajobs_key",
           note="US federal jobs; free API key + your email from developer.usajobs.gov"),
]

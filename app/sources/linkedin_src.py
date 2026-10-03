from __future__ import annotations

import httpx

from .. import linkedin
from ..jobmodel import Job
from .base import JobQuery, Source, SourceError


async def fetch(q: JobQuery, client: httpx.AsyncClient, on_progress=None) -> list[Job]:
    from . import aggregate          # local import: aggregate imports the source registry
    warnings: list[str] = []
    core = aggregate.core_tokens(q.title)

    def card_ok(j: Job) -> bool:     # card has title, company, location, date
        return (not q.strict or aggregate.relevance(j, core) >= 0.75) and aggregate.filters_ok(j, q)[0]

    def detail_ok(j: Job) -> bool:   # after details: employment type etc. are known
        return aggregate.filters_ok(j, q)[0]
    try:
        # module attribute lookup so tests can monkeypatch linkedin.search_jobs
        jobs = await linkedin.search_jobs(q.title, q.location, q.count, q.hours, on_progress, client,
                                          experience=q.experience, job_types=q.job_types, workplace=q.workplace,
                                          sort=q.sort, warnings=warnings, prefilter=card_ok, postfilter=detail_ok)
    except linkedin.LinkedInError as e:
        raise SourceError(str(e), e.kind)
    for j in jobs:
        j.source = "linkedin"
    if warnings and jobs:
        jobs[0].extra.setdefault("_warnings", []).extend(warnings)
    return list(jobs)


SOURCES = [Source("linkedin", "LinkedIn", "search", "www.linkedin.com", fetch, timeout=300,
                  note="Largest volume; public pages may be rate-limited")]

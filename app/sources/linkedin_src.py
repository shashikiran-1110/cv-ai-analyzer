from __future__ import annotations

import httpx

from .. import linkedin
from ..jobmodel import Job
from .base import JobQuery, Source, SourceError


async def fetch(q: JobQuery, client: httpx.AsyncClient, on_progress=None) -> list[Job]:
    warnings: list[str] = []
    try:
        # module attribute lookup so tests can monkeypatch linkedin.search_jobs
        jobs = await linkedin.search_jobs(q.title, q.location, q.count, q.hours, on_progress,
                                          experience=q.experience, job_types=q.job_types, workplace=q.workplace,
                                          sort=q.sort, warnings=warnings)
    except linkedin.LinkedInError as e:
        raise SourceError(str(e), e.kind)
    for j in jobs:
        j.source = "linkedin"
    if warnings and jobs:
        jobs[0].extra.setdefault("_warnings", []).extend(warnings)
    return list(jobs)


SOURCES = [Source("linkedin", "LinkedIn", "search", "www.linkedin.com", fetch, timeout=300,
                  note="Largest volume; public pages may be rate-limited")]

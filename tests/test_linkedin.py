from pathlib import Path

import httpx
import pytest

from app import linkedin

FX = Path(__file__).parent / "fixtures"


def test_parse_search_page():
    jobs = linkedin.parse_search_page((FX / "search.html").read_text())
    assert [j.id for j in jobs] == ["4001111111", "4002222222"]
    j = jobs[0]
    assert j.title == "Senior Data Engineer"
    assert j.company == "Acme Corp"
    assert j.location.startswith("London")
    assert j.posted == "2026-09-30"
    assert j.url.endswith("4001111111") and "?" not in j.url


def test_parse_detail():
    d = linkedin.parse_detail((FX / "detail.html").read_text())
    assert "Build data pipelines on AWS" in d["description"]
    assert "• 5+ years of experience" in d["description"]
    assert d["seniority"] == "Mid-Senior level"
    assert d["employment_type"] == "Full-time"


@pytest.mark.asyncio
async def test_search_jobs_pages_and_details():
    search_html = (FX / "search.html").read_text()
    detail_html = (FX / "detail.html").read_text()
    calls = {"search": 0, "detail": 0, "params": []}

    def handler(request: httpx.Request) -> httpx.Response:
        if "seeMoreJobPostings" in request.url.path:
            calls["search"] += 1
            calls["params"].append(dict(request.url.params))
            return httpx.Response(200, text=search_html if calls["search"] == 1 else "")
        calls["detail"] += 1
        return httpx.Response(200, text=detail_html)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        events = []

        async def cb(stage, done, total):
            events.append(stage)

        jobs = await linkedin.search_jobs("data engineer", "London", 5, hours=24, on_progress=cb, client=client)
    assert len(jobs) == 2                      # only 2 exist; stops after empty pages
    assert all(len(j.description) > 80 for j in jobs)
    assert calls["params"][0]["f_TPR"] == "r86400"
    assert calls["params"][0]["keywords"] == "data engineer"
    assert "details" in events

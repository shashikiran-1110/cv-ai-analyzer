"""ROADMAP Phase 2: persistence, runs/events, caching, rate limits, privacy endpoints."""
import asyncio
import json
import time

import httpx
from httpx import ASGITransport, AsyncClient

from app import linkedin, main
from app.storage import db
from tests.test_api import DESC, HDR, _analyzed, _mock_llm, _run_events, wait_done, client  # noqa: F401
from app.jobmodel import Job


def _restart():
    """Simulate a server restart: drop every in-memory store."""
    main.SEARCHES.clear()
    main.ANALYSES.clear()


async def test_report_survives_restart_and_refresh(client, resume_pdf):  # noqa: F811
    async with client as c:
        a = await _analyzed(c, resume_pdf)
        aid = a["analysis_id"]
        _restart()
        r = await c.get(f"/api/analysis/{aid}")
        assert r.status_code == 200 and r.json()["summary"]["job_count"] == a["summary"]["job_count"]
        assert [j["id"] for j in r.json()["jobs"]] == [j["id"] for j in a["jobs"]]
        _restart()
        rs = await c.post(f"/api/analysis/{aid}/rescore", json={"extra_skills": ["Kubernetes"]})
        assert rs.status_code == 200 and rs.json()["extra_skills"] == ["Kubernetes"]
        _restart()
        assert (await c.get(f"/api/analysis/{aid}")).json()["extra_skills"] == ["Kubernetes"]
        _restart()
        assert (await c.get(f"/api/analysis/{aid}/job/{a['jobs'][0]['id']}")).json()["description"]
        assert (await c.get("/api/analysis/" + "0" * 32)).status_code == 404
        assert (await c.get("/api/analysis/../etc")).status_code == 404


async def test_search_survives_restart(client):  # noqa: F811
    async with client as c:
        sid = (await c.post("/api/search", json={"title": "data engineer", "count": 3})).json()["search_id"]
        await wait_done(c, sid)
        _restart()
        s = (await c.get(f"/api/search/{sid}")).json()
        assert s["status"] == "done" and len(s["jobs"]) == 3


async def test_repeat_search_is_served_from_cache(client, monkeypatch):  # noqa: F811
    calls = []

    async def slow(title, location, count, hours=None, on_progress=None, client=None, **kw):
        calls.append(title)
        await asyncio.sleep(0.3)
        return [Job(id=str(i), title="Data Engineer", company=f"C{i}", location="London", description=DESC) for i in range(count)]
    monkeypatch.setattr(linkedin, "search_jobs", slow)
    body = {"title": "data engineer", "count": 4, "location": "London"}
    async with client as c:
        first = (await c.post("/api/search", json=body)).json()
        assert first["cached"] is False
        await wait_done(c, first["search_id"])
        t0 = time.perf_counter()
        second = (await c.post("/api/search", json=body)).json()
        s = (await c.get(f"/api/search/{second['search_id']}")).json()
        elapsed = time.perf_counter() - t0
        calls_after_repeat = len(calls)
        third = (await c.post("/api/search", json={**body, "location": "Paris"})).json()
    assert second["cached"] is True and s["status"] == "done" and s["cached"] and len(s["jobs"]) == 4
    assert elapsed < 2.0 and calls_after_repeat == 1                    # acceptance: repeat search < 2 s, no refetch
    assert third["cached"] is False


async def test_search_streams_events(client):  # noqa: F811
    async with client as c:
        sid = (await c.post("/api/search", json={"title": "data engineer", "count": 2})).json()["search_id"]
        events = await _run_events(c, sid)
    kinds = [e for e, _ in events]
    assert "source.progress" in kinds and kinds[-2:] == ["jobs.ready", "run.finished"]
    assert dict(events)["jobs.ready"]["count"] == 2


async def test_analyze_is_fast_with_slow_ai(client, resume_pdf, monkeypatch):  # noqa: F811
    async def many(title, location, count, hours=None, on_progress=None, client=None, **kw):
        return [Job(id=str(i), title="Data Engineer", company=f"C{i}", description=DESC + f" ref {i}") for i in range(100)]
    monkeypatch.setattr(linkedin, "search_jobs", many)

    async def slow_ai(request):
        await asyncio.sleep(2.5)   # the AI call takes 2.5 s (async, like a real network wait)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(
            {"summary": "s", "strengths": ["a"], "improvements": ["b"], "skills_to_learn": []})}}]})
    _mock_llm(monkeypatch, slow_ai)
    async with client as c:
        sid = (await c.post("/api/search", json={"title": "data engineer", "count": 100})).json()["search_id"]
        await wait_done(c, sid)
        t0 = time.perf_counter()
        r = await c.post("/api/analyze", data={"search_id": sid, "use_ai": "true"}, headers=HDR,
                         files={"resume": ("cv.pdf", resume_pdf, "application/pdf")})
        elapsed = time.perf_counter() - t0
        assert r.status_code == 200 and r.json()["summary"]["job_count"] == 100
        assert elapsed < 3.0, elapsed                                    # acceptance: < 3 s for 100 jobs, AI on
        events = dict(await _run_events(c, r.json()["insights_run_id"]))
    assert events["insight.ready"]["insights"]["source"] == "openai"


async def test_rate_limit_on_searches(client, monkeypatch):  # noqa: F811
    monkeypatch.setenv("RATE_LIMIT_SEARCH_PER_HOUR", "2")
    async with client as c:
        codes = [(await c.post("/api/search", json={"title": f"role number {i}", "count": 1})).status_code for i in range(3)]
    assert codes == [200, 200, 429]


async def test_owner_cookie_export_and_delete(client, resume_pdf):  # noqa: F811
    async with client as c:
        a = await _analyzed(c, resume_pdf)
        assert c.cookies.get("cvm_sid")
        exp = (await c.get("/api/me/export")).json()
        assert [x["id"] for x in exp["analyses"]] == [a["analysis_id"]] and exp["resumes"][0]["text"].startswith("Jane Doe")
        other = AsyncClient(transport=ASGITransport(app=main.app), base_url="http://t")
        assert (await other.get("/api/me/export")).json()["analyses"] == []          # another visitor sees nothing
        d = (await c.delete("/api/me")).json()["deleted"]
        assert d["analyses"] == 1 and d["resumes"] == 1
        _restart()
        assert (await c.get(f"/api/analysis/{a['analysis_id']}")).status_code == 404


async def test_security_headers(client):  # noqa: F811
    async with client as c:
        r = await c.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff" and "referrer-policy" in r.headers


def test_retention_purge(monkeypatch):
    monkeypatch.setenv("ANON_RETENTION_DAYS", "-1")             # everything is already expired
    db.save_resume("r" * 32, "text", "sha")
    db.save_analysis("a" * 32, {"jobs_full": [], "resume_id": "r" * 32, "result": {}})
    assert db.purge_expired()["analyses"] == 1 and db.load_resume("r" * 32) is None


async def test_board_feed_is_cached():
    from app.sources import BY_ID, JobQuery
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=[{"legal": "x"}, {"id": "1", "position": "Data Engineer", "company": "A"}])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        await BY_ID["remoteok"].fetch(JobQuery(title="x"), c)
        await BY_ID["remoteok"].fetch(JobQuery(title="y"), c)
    assert len(calls) == 1


async def test_resume_id_flow_survives_refresh(client, resume_pdf):  # noqa: F811
    async with client as c:
        p = (await c.post("/api/resume/preview", files={"resume": ("cv.pdf", resume_pdf, "application/pdf")})).json()
        sid = (await c.post("/api/search", json={"title": "data engineer", "count": 2})).json()["search_id"]
        await wait_done(c, sid)
        _restart()
        r = await c.post("/api/analyze", data={"search_id": sid, "resume_id": p["resume_id"]})
        assert r.status_code == 200 and r.json()["resume_id"] == p["resume_id"]
        assert (await c.post("/api/analyze", data={"search_id": sid, "resume_id": "f" * 32})).status_code == 404

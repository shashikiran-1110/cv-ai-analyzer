import asyncio
import json

import pytest
from httpx import ASGITransport, AsyncClient

from app import linkedin, main
from tests.conftest import make_pdf

DESC = (
    "Requirements\n- 3+ years of experience\n- Python and SQL\n- AWS and Docker\n- Airflow\n"
    "Nice to have\n- Kubernetes\n- Terraform\n" + "Join our team. " * 10
)


@pytest.fixture
def client(monkeypatch):
    async def fake_search(title, location, count, hours=None, on_progress=None, client=None):
        if title == "boom":
            raise linkedin.LinkedInError("LinkedIn is rate-limiting requests right now.")
        await on_progress("details", 1, 1)
        return [linkedin.Job(id=str(i), title="Data Engineer", company=f"Co{i}", location="Remote",
                             url=f"https://x/{i}", description=DESC) for i in range(count)]

    monkeypatch.setattr(linkedin, "search_jobs", fake_search)
    main.SEARCHES.clear()
    return AsyncClient(transport=ASGITransport(app=main.app), base_url="http://t")


async def wait_done(c, sid):
    for _ in range(50):
        r = (await c.get(f"/api/search/{sid}")).json()
        if r["status"] != "running":
            return r
        await asyncio.sleep(0.02)
    raise AssertionError("search never finished")


async def test_full_flow(client, resume_pdf):
    async with client as c:
        sid = (await c.post("/api/search", json={"title": "data engineer", "location": "Remote", "count": 5,
                                                 "time_range": "custom", "custom_hours": 48})).json()["search_id"]
        s = await wait_done(c, sid)
        assert s["status"] == "done" and len(s["jobs"]) == 5 and "description" not in s["jobs"][0]
        assert s["query"]["hours"] == 48

        r = await c.post("/api/analyze", data={"search_id": sid, "threshold": "60", "use_ai": "false"},
                         files={"resume": ("cv.pdf", resume_pdf, "application/pdf")})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["summary"]["job_count"] == 5
        assert body["summary"]["qualifying"] == 5
        assert body["jobs"][0]["score"] >= 60
        assert body["insights"]["source"] == "local"
        assert {g["skill"] for g in body["summary"]["skill_gaps"]} == {"Kubernetes", "Terraform"}
        assert body["insights"]["skills_to_learn"]

        r = await c.post("/api/analyze", data={"search_id": sid, "job_ids": json.dumps(["1", "2"])},
                         files={"resume": ("cv.pdf", resume_pdf, "application/pdf")})
        assert r.json()["summary"]["job_count"] == 2


async def test_validation_and_errors(client, resume_pdf):
    async with client as c:
        assert (await c.post("/api/search", json={"title": "x", "count": 5})).status_code == 422
        assert (await c.post("/api/search", json={"title": "data", "count": 500})).status_code == 422
        assert (await c.post("/api/search", json={"title": "data", "time_range": "custom"})).status_code == 422
        assert (await c.post("/api/search", json={"title": "data", "time_range": "bogus"})).status_code == 422
        assert (await c.get("/api/search/nope")).status_code == 404

        sid = (await c.post("/api/search", json={"title": "boom", "count": 3})).json()["search_id"]
        s = await wait_done(c, sid)
        assert s["status"] == "error" and "rate-limiting" in s["error"]

        ok = (await c.post("/api/search", json={"title": "data engineer", "count": 2})).json()["search_id"]
        await wait_done(c, ok)
        bad = await c.post("/api/analyze", data={"search_id": ok},
                           files={"resume": ("cv.pdf", b"not a pdf at all", "application/pdf")})
        assert bad.status_code == 422 and "PDF" in bad.json()["detail"]
        empty = await c.post("/api/analyze", data={"search_id": ok},
                             files={"resume": ("cv.pdf", make_pdf(["hi"]), "application/pdf")})
        assert empty.status_code == 422 and "text" in empty.json()["detail"]
        gone = await c.post("/api/analyze", data={"search_id": "zzz"},
                            files={"resume": ("cv.pdf", resume_pdf, "application/pdf")})
        assert gone.status_code == 404


async def test_ai_failure_falls_back(client, resume_pdf, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    async def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr("app.insights.llm_insights", boom)
    async with client as c:
        assert (await c.get("/api/config")).json()["ai_available"] is True
        sid = (await c.post("/api/search", json={"title": "data engineer", "count": 2})).json()["search_id"]
        await wait_done(c, sid)
        r = await c.post("/api/analyze", data={"search_id": sid, "use_ai": "true"},
                         files={"resume": ("cv.pdf", resume_pdf, "application/pdf")})
        assert r.status_code == 200
        ins = r.json()["insights"]
        assert ins["source"] == "local" and "ai_error" in ins


async def test_claude_json_parsing():
    from app.insights import _extract_json
    assert _extract_json('Here you go:\n```json\n{"a": 1}\n```')["a"] == 1


async def test_openai_provider(client, resume_pdf, monkeypatch):
    import httpx
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert main.config.ai_provider() == "openai"
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        out = {"summary": "Solid fit.", "strengths": ["Python"], "improvements": ["Add metrics"],
               "skills_to_learn": [{"skill": "Kubernetes", "why": "w", "how": "h"}]}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(out)}}]})

    real = httpx.AsyncClient
    monkeypatch.setattr("app.insights.httpx.AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    async with client as c:
        sid = (await c.post("/api/search", json={"title": "data engineer", "count": 2})).json()["search_id"]
        await wait_done(c, sid)
        r = await c.post("/api/analyze", data={"search_id": sid, "use_ai": "true"},
                         files={"resume": ("cv.pdf", resume_pdf, "application/pdf")})
    ins = r.json()["insights"]
    assert ins["source"] == "openai" and ins["summary"] == "Solid fit."
    assert seen["auth"] == "Bearer sk-test" and seen["body"]["model"] == "gpt-5.6-luna"
    assert ins["skills_to_learn"][0]["jobs"] == 2     # joined with local gap counts

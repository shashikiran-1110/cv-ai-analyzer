import asyncio
import json

import pytest
from httpx import ASGITransport, AsyncClient

from app import linkedin, llm, main
from tests.conftest import make_pdf

DESC = (
    "Requirements\n- 3+ years of experience\n- Python and SQL\n- AWS and Docker\n- Airflow\n"
    "Nice to have\n- Kubernetes\n- Terraform\n" + "Join our team. " * 10
)


@pytest.fixture
def client(monkeypatch):
    async def fake_search(title, location, count, hours=None, on_progress=None, client=None, **kw):
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


async def _analyzed(c, resume_pdf, headers=None, **data):
    sid = (await c.post("/api/search", json={"title": "data engineer", "count": 3})).json()["search_id"]
    await wait_done(c, sid)
    r = await c.post("/api/analyze", data={"search_id": sid, **data}, headers=headers or {},
                     files={"resume": ("cv.pdf", resume_pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    return r.json()


async def test_search_filters_forwarded(client, monkeypatch):
    seen = {}

    async def fake(title, location, count, hours=None, on_progress=None, client=None, **kw):
        seen.update(kw)
        return []

    monkeypatch.setattr(linkedin, "search_jobs", fake)
    async with client as c:
        r = await c.post("/api/search", json={"title": "data engineer", "experience": ["entry", "mid_senior"],
                                              "job_types": ["contract"], "workplace": ["remote"], "sort": "relevant"})
        await wait_done(c, r.json()["search_id"])
        assert (await c.post("/api/search", json={"title": "x y", "workplace": ["moon"]})).status_code == 422
    assert seen.pop("warnings") == []
    assert callable(seen.pop("prefilter")) and callable(seen.pop("postfilter"))
    assert seen == {"experience": ["entry", "mid_senior"], "job_types": ["contract"],
                    "workplace": ["remote"], "sort": "relevant"}


async def test_paste_text_and_rescore(client, resume_pdf):
    from tests.conftest import RESUME_LINES
    async with client as c:
        sid = (await c.post("/api/search", json={"title": "data engineer", "count": 3})).json()["search_id"]
        await wait_done(c, sid)
        r = await c.post("/api/analyze", data={"search_id": sid, "resume_text": "\n".join(RESUME_LINES),
                                               "extra_skills": json.dumps(["k8s", "nonsense skill"])})
        body = r.json()
        assert r.status_code == 200 and body["extra_skills"] == ["Kubernetes"] and body["unknown_skills"] == ["nonsense skill"]
        aid = body["analysis_id"]
        gaps = {g["skill"] for g in body["summary"]["skill_gaps"]}
        assert gaps == {"Terraform"}                      # Kubernetes was supplied by the user
        before = body["jobs"][0]["score"]
        r2 = await c.post(f"/api/analysis/{aid}/rescore", json={"extra_skills": ["Kubernetes", "terraform"]})
        assert r2.json()["jobs"][0]["score"] > before and not r2.json()["summary"]["skill_gaps"]
        assert (await c.post("/api/analysis/nope/rescore", json={})).status_code == 404
        d = await c.get(f"/api/analysis/{aid}/job/0")
        assert "Requirements" in d.json()["description"]
        assert (await c.get(f"/api/analysis/{aid}/job/999")).status_code == 404
        no_resume = await c.post("/api/analyze", data={"search_id": sid})
        assert no_resume.status_code == 422


async def _run_events(c, run_id):
    """Read a run's SSE stream to the end: [(event, data), ...]."""
    r = await c.get(f"/api/runs/{run_id}/events")
    out, ev = [], None
    for line in r.text.splitlines():
        if line.startswith("event: "):
            ev = line[7:]
        elif line.startswith("data: ") and ev:
            out.append((ev, json.loads(line[6:])))
            ev = None
    return out


def _mock_llm(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(llm, "_client", lambda: real(transport=httpx.MockTransport(handler)))


import httpx  # noqa: E402

HDR = {"X-AI-Provider": "openai", "X-AI-Key": "sk-secret-123", "X-AI-Model": "gpt-5.6-luna"}


async def test_ai_insights_via_browser_key(client, resume_pdf, monkeypatch):
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        out = {"summary": "Solid fit.", "strengths": ["Python"], "improvements": ["Add metrics"],
               "skills_to_learn": [{"skill": "Kubernetes", "why": "w", "how": "h"}]}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(out)}}]})

    _mock_llm(monkeypatch, handler)
    async with client as c:
        body = await _analyzed(c, resume_pdf, HDR, use_ai="true")
        assert body["insights"]["source"] == "local" and body["insights"]["pending"]   # results first, AI later
        events = await _run_events(c, body["insights_run_id"])
        assert [e for e, _ in events][-2:] == ["insight.ready", "run.finished"]
        ins = dict(events)["insight.ready"]["insights"]
        restored = (await c.get(f"/api/analysis/{body['analysis_id']}")).json()
    assert restored["insights"]["source"] == "openai" and restored["insights_run_id"] is None
    assert ins["source"] == "openai" and ins["summary"] == "Solid fit."
    assert seen["auth"] == "Bearer sk-secret-123" and seen["body"]["model"] == "gpt-5.6-luna"
    assert ins["skills_to_learn"][0]["jobs"] == 3
    assert "sk-secret-123" not in json.dumps(body)


async def test_ai_failure_falls_back_without_leaking_key(client, resume_pdf, monkeypatch):
    def handler(request):
        return httpx.Response(401, json={"error": {"message": "Incorrect API key provided: sk-secret-123"}})

    _mock_llm(monkeypatch, handler)
    async with client as c:
        body = await _analyzed(c, resume_pdf, HDR, use_ai="true")
        events = dict(await _run_events(c, body["insights_run_id"]))
    ins = events["insight.ready"]["insights"]
    assert ins["source"] == "local"
    assert "rejected the API key" in ins["ai_error"]
    assert "sk-secret-123" not in json.dumps(body) + json.dumps(events)


async def test_verify_endpoint(client, monkeypatch):
    codes = iter([200, 401, 404, 403])
    _mock_llm(monkeypatch, lambda req: httpx.Response(next(codes), json={"error": {"message": "x sk-secret-123"}}))
    async with client as c:
        assert (await c.post("/api/ai/verify")).json()["ok"] is False        # no key
        ok = (await c.post("/api/ai/verify", headers=HDR)).json()
        assert ok["ok"] and "verified" in ok["message"]
        bad = (await c.post("/api/ai/verify", headers=HDR)).json()
        assert not bad["ok"] and "rejected" in bad["message"]
        nomodel = (await c.post("/api/ai/verify", headers=HDR)).json()
        assert not nomodel["ok"] and "gpt-5.6-luna" in nomodel["message"] and "sk-secret" not in nomodel["message"]
        restricted = (await c.post("/api/ai/verify", headers=HDR)).json()
        assert restricted["ok"] and restricted["warning"]
        r = await c.post("/api/ai/verify", headers={**HDR, "X-AI-Provider": "bogus"})
        assert r.status_code == 422


def _sse_body(chunks):
    lines = [f"data: {json.dumps({'choices': [{'delta': {'content': t}}]})}\n\n" for t in chunks]
    return "".join(lines) + "data: [DONE]\n\n"


async def test_chat_and_tool_stream(client, resume_pdf, monkeypatch):
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, text=_sse_body(["Hello ", "world"]), headers={"content-type": "text/event-stream"})

    _mock_llm(monkeypatch, handler)
    async with client as c:
        body = await _analyzed(c, resume_pdf)
        aid = body["analysis_id"]
        msgs = {"messages": [{"role": "user", "content": "What should I learn?"}], "job_id": "0"}
        assert (await c.post(f"/api/analysis/{aid}/chat", json=msgs)).status_code == 401     # no key
        r = await c.post(f"/api/analysis/{aid}/chat", json=msgs, headers=HDR)
        assert r.status_code == 200 and "text/event-stream" in r.headers["content-type"]
        pieces = [json.loads(l[6:])["t"] for l in r.text.splitlines() if l.startswith("data: {")]
        assert "".join(pieces) == "Hello world" and "data: [DONE]" in r.text
        system = captured["body"]["messages"][0]["content"]
        assert "<resume>" in system and "Jane Doe" in system and "<job>" in system and "Data Engineer" in system
        assert captured["body"]["stream"] is True

        bad = {"messages": [{"role": "assistant", "content": "hi"}]}
        assert (await c.post(f"/api/analysis/{aid}/chat", json=bad, headers=HDR)).status_code == 422

        t = await c.post(f"/api/analysis/{aid}/tool", json={"job_id": "0", "kind": "cover_letter"}, headers=HDR)
        assert "world" in t.text and "[DONE]" in t.text and "cover letter" in captured["body"]["messages"][-1]["content"].lower()
        assert (await c.post(f"/api/analysis/{aid}/tool", json={"job_id": "0", "kind": "nope"}, headers=HDR)).status_code == 422


async def test_stream_error_event(client, resume_pdf, monkeypatch):
    _mock_llm(monkeypatch, lambda req: httpx.Response(429, json={"error": {"message": "quota"}}))
    async with client as c:
        aid = (await _analyzed(c, resume_pdf))["analysis_id"]
        r = await c.post(f"/api/analysis/{aid}/chat", headers=HDR,
                         json={"messages": [{"role": "user", "content": "hi"}]})
    assert "event: error" in r.text and "rate limit" in r.text.lower()


async def test_anthropic_stream_and_complete(monkeypatch):
    cfg = llm.LLMConfig("anthropic", "ak-1", "claude-sonnet-5-5")
    sse = "".join(f"event: x\ndata: {json.dumps(e)}\n\n" for e in [
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi "}},
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "there"}},
        {"type": "message_stop"}])
    seen = {}

    def handler(request):
        seen["h"] = dict(request.headers)
        payload = json.loads(request.content)
        if payload["stream"]:
            return httpx.Response(200, text=sse)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "done"}]})

    _mock_llm(monkeypatch, handler)
    out = [p async for p in llm.stream(cfg, "sys", [{"role": "user", "content": "q"}])]
    assert "".join(out) == "Hi there" and seen["h"]["x-api-key"] == "ak-1"
    assert await llm.complete(cfg, "sys", [{"role": "user", "content": "q"}]) == "done"


async def test_sources_listing_and_validation(client):
    async with client as c:
        ids = [x["id"] for x in (await c.get("/api/sources")).json()]
        assert {"linkedin", "remotive", "greenhouse", "adzuna", "urls"} <= set(ids)
        bad = await c.post("/api/search", json={"title": "data engineer", "sources": ["nope"]})
        assert bad.status_code == 422 and "nope" in bad.json()["detail"]
        r = await c.post("/api/search", json={"title": "data engineer", "sources": ["greenhouse"]})
        assert r.status_code == 422 and "company" in r.json()["detail"]
        r = await c.post("/api/search", json={"title": "data engineer", "sources": ["adzuna"]})
        assert r.status_code == 422 and "Adzuna" in r.json()["detail"]
        r = await c.post("/api/search", json={"title": "data engineer", "sources": ["urls"]})
        assert r.status_code == 422 and "URL" in r.json()["detail"]


async def test_all_sources_failing_reports_each_reason(client, monkeypatch):
    async def fail(*a, **k):
        raise linkedin.LinkedInError("Can't connect to linkedin.com (ProxyError).", "network")
    monkeypatch.setattr(linkedin, "search_jobs", fail)
    real = httpx.AsyncClient

    def boom(request):
        raise httpx.ConnectError("blocked")
    monkeypatch.setattr("app.sources.aggregate.httpx.AsyncClient", lambda **kw: real(transport=httpx.MockTransport(boom)))
    async with client as c:
        sid = (await c.post("/api/search", json={"title": "data engineer", "sources": ["linkedin", "remotive"]})).json()["search_id"]
        s = await wait_done(c, sid)
    assert s["status"] == "error" and "linkedin.com" in s["error"] and "remotive.com" in s["error"]
    assert {x["id"]: x["status"] for x in s["sources"]} == {"linkedin": "error", "remotive": "error"}


async def test_manual_and_sample_searches(client, resume_pdf):
    async with client as c:
        bad = await c.post("/api/search/manual", json={"jobs": [{"title": "X", "description": "short"}]})
        assert bad.status_code == 422
        desc = "Requirements\n- Python and SQL\n- Airflow and Spark\n- 3+ years of experience\n" + "More detail here. " * 5
        r = await c.post("/api/search/manual", json={"jobs": [{"title": "Data Engineer", "company": "Acme", "description": desc}]})
        sid = r.json()["search_id"]
        s = (await c.get(f"/api/search/{sid}")).json()
        assert s["status"] == "done" and s["jobs"][0]["source"] == "manual"
        a = await c.post("/api/analyze", data={"search_id": sid}, files={"resume": ("cv.pdf", resume_pdf, "application/pdf")})
        assert a.status_code == 200 and a.json()["jobs"][0]["score"] >= 60

        sid = (await c.post("/api/search/sample", json={"title": "Data Engineer"})).json()["search_id"]
        s = (await c.get(f"/api/search/{sid}")).json()
        titles = [j["title"] for j in s["jobs"]]
        assert all("Data" in t or "Engineer" in t for t in titles) and all(j["source"] == "sample" for j in s["jobs"])
        a = (await c.post("/api/analyze", data={"search_id": sid}, files={"resume": ("cv.pdf", resume_pdf, "application/pdf")})).json()
        assert {"requirements", "semantic"} <= set(a["jobs"][0]["components"])
        assert a["jobs"][0]["requirements"] and "by_source" in a["summary"]


async def test_resume_preview(client, resume_pdf):
    async with client as c:
        r = (await c.post("/api/resume/preview", files={"resume": ("cv.pdf", resume_pdf, "application/pdf")})).json()
        assert {"Python", "SQL", "Airflow"} <= set(r["skills"]) and r["years"] >= 6 and r["headline"].startswith("Jane Doe")
        assert (await c.post("/api/resume/preview", data={"resume_text": "too short"})).status_code == 422
        bad = await c.post("/api/resume/preview", files={"resume": ("cv.pdf", b"nope", "application/pdf")})
        assert bad.status_code == 422 and "PDF" in bad.json()["detail"]


async def test_diagnose_reports_blocked_hosts(client, monkeypatch):
    real = httpx.AsyncClient

    def boom(request):
        raise httpx.ConnectError("blocked")
    monkeypatch.setattr("app.main.httpx.AsyncClient", lambda **kw: real(transport=httpx.MockTransport(boom), **{k: v for k, v in kw.items() if k == "headers"}))
    async def probe():
        return {"ok": False, "kind": "network", "message": "Can't connect to linkedin.com"}
    monkeypatch.setattr(linkedin, "probe", probe)
    async with client as c:
        d = (await c.get("/api/diagnose")).json()
    assert d["api"]["ok"] and not d["checks"]["linkedin"]["ok"]
    assert not d["checks"]["remotive"]["ok"] and "remotive.com" in d["checks"]["remotive"]["message"]
    assert "OpenAI API" in d["checks"] and d["ai_key"]["ok"] is False

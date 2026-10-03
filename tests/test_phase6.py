"""Phase 6: accounts, tracker, watches + digests, company resolver, more ATS sources, market, extension, ops."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app import main
from app.api import companies, watches
from app.runtime import mailer, metrics, scheduler
from app.sources import BY_ID, JobQuery
from app.storage import db
from tests.test_api import _analyzed, client  # noqa: F401  (fixture reuse)

RECENT = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()


def _fresh():
    return AsyncClient(transport=ASGITransport(app=main.app), base_url="http://t")


# ---------- accounts ----------
async def test_magic_link_sign_in_moves_anonymous_work(client, resume_pdf, monkeypatch):  # noqa: F811
    monkeypatch.setenv("DEV_LOGIN_LINKS", "true")
    mailer.OUTBOX.clear()
    async with client as c:
        a = await _analyzed(c, resume_pdf)
        assert (await c.get("/api/me")).json()["kind"] == "anonymous"
        assert (await c.post("/api/auth/request", json={"email": "not-an-email"})).status_code == 422
        r = (await c.post("/api/auth/request", json={"email": "Ada@Example.com"})).json()
        assert r["delivery"] == "console" and mailer.OUTBOX[-1]["to"] == "ada@example.com"
        link = r["dev_link"]
        assert link in mailer.OUTBOX[-1]["text"]
        v = await c.get(link.replace("http://t", ""), follow_redirects=False)
        assert v.status_code == 303 and v.headers["location"] == "/settings?signin=ok"
        me = (await c.get("/api/me")).json()
        assert me["kind"] == "user" and me["user"]["email"] == "ada@example.com"
        exported = (await c.get("/api/me/export")).json()
        assert exported["resumes"] and exported["analyses"][0]["id"] == a["analysis_id"]   # anonymous work moved over
        again = await c.get(link.replace("http://t", ""), follow_redirects=False)
        assert again.headers["location"] == "/settings?signin=expired"                       # single use
        await c.post("/api/auth/logout")
        assert (await c.get("/api/me")).json()["kind"] == "anonymous"
    monkeypatch.setenv("DEV_LOGIN_LINKS", "false")
    async with _fresh() as c:
        assert "dev_link" not in (await c.post("/api/auth/request", json={"email": "b@example.com"})).json()


# ---------- tracker ----------
async def test_tracker_crud_isolation_and_csv(client):  # noqa: F811
    async with client as c:
        r = (await c.post("/api/tracker", json={"job_id": "j1", "title": "=HYPERLINK(\"evil\")", "company": "Acme",
                                                "score": 72})).json()
        assert r["stage"] == "saved" and r["history"][0]["stage"] == "saved"
        assert (await c.post("/api/tracker", json={"job_id": "j1", "title": "dup"})).json()["id"] == r["id"]   # no duplicates
        p = (await c.patch(f"/api/tracker/{r['id']}", json={"stage": "applied", "notes": "sent CV"})).json()
        assert p["stage"] == "applied" and [h["stage"] for h in p["history"]] == ["saved", "applied"]
        assert (await c.patch(f"/api/tracker/{r['id']}", json={"stage": "hired"})).status_code == 422
        csv = (await c.get("/api/tracker.csv")).text
        assert "'=HYPERLINK" in csv and "applied" in csv                                  # formula injection neutralised
        async with _fresh() as o:
            assert (await o.get("/api/tracker")).json()["items"] == []
            assert (await o.patch(f"/api/tracker/{r['id']}", json={"stage": "offer"})).status_code == 404
        assert (await c.delete(f"/api/tracker/{r['id']}")).json() == {"deleted": 1}


# ---------- watches ----------
async def test_watch_digest_reports_only_new_jobs(client, resume_pdf, monkeypatch):  # noqa: F811
    from app import linkedin
    async with client as c:
        a = await _analyzed(c, resume_pdf)
        assert (await c.post("/api/watches", json={"analysis_id": a["analysis_id"], "email": True})).status_code == 401
        w = (await c.post("/api/watches", json={"analysis_id": a["analysis_id"], "threshold": 50})).json()
        assert w["frequency"] == "daily" and w["query"]["sources"] == ["linkedin"]
        d = (await c.post(f"/api/watches/{w['id']}/run")).json()
        assert d["new"] == 0                                    # the report's jobs were already seen

        async def more(title, location, count, hours=None, on_progress=None, client=None, **kw):
            return [linkedin.Job(id=f"n{i}", title="Data Engineer", company=f"New{i}", location="Remote", url=f"https://x/n{i}",
                                 description=main_desc()) for i in range(2)]
        monkeypatch.setattr(linkedin, "search_jobs", more)
        d = (await c.post(f"/api/watches/{w['id']}/run")).json()
        assert d["new"] == 2 and d["qualifying"] == 2 and d["matches"][0]["score"] >= 50
        assert (await c.post(f"/api/watches/{w['id']}/run")).json()["new"] == 0
        lst = (await c.get("/api/watches")).json()
        assert lst["items"][0]["latest"]["new"] == 0 and len((await c.get(f"/api/watches/{w['id']}/digests")).json()["items"]) == 3
        async with _fresh() as o:
            assert (await o.post(f"/api/watches/{w['id']}/run")).status_code == 404


def main_desc():
    from tests.test_api import DESC
    return DESC


async def test_due_watches_run_and_email_when_signed_in(client, resume_pdf, monkeypatch):  # noqa: F811
    from app import linkedin
    monkeypatch.setenv("DEV_LOGIN_LINKS", "true")
    mailer.OUTBOX.clear()
    async with client as c:
        a = await _analyzed(c, resume_pdf)
        link = (await c.post("/api/auth/request", json={"email": "w@example.com"})).json()["dev_link"]
        await c.get(link.replace("http://t", ""), follow_redirects=False)
        w = (await c.post("/api/watches", json={"analysis_id": a["analysis_id"], "email": True, "threshold": 40})).json()
        assert w["email"] is True

        async def more(title, location, count, hours=None, on_progress=None, client=None, **kw):
            return [linkedin.Job(id="due1", title="Data Engineer", company="Due", location="Remote", url="https://x/due1",
                                 description=main_desc())]
        monkeypatch.setattr(linkedin, "search_jobs", more)
        assert await watches.run_due() == 0                     # not due yet
        assert await watches.run_due(now=w["next_run_at"] + 1) == 1
    assert mailer.OUTBOX[-1]["to"] == "w@example.com" and "Due" in mailer.OUTBOX[-1]["text"]


# ---------- company resolver ----------
async def test_company_resolver_probes_and_caches(client, monkeypatch):  # noqa: F811
    calls = []

    def handler(req: httpx.Request):
        calls.append(str(req.url))
        if req.url.host == "boards-api.greenhouse.io" and "/acmerobotics/" in req.url.path:
            return httpx.Response(200, json={"jobs": [{"id": 1}, {"id": 2}]})
        if req.url.host == "acme-robotics.recruitee.com":
            return httpx.Response(200, json={"offers": [{"id": 1}]})
        return httpx.Response(404)
    real = companies.resolve

    async def fake_resolve(name, client=None):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as mc:
            return await real(name, mc)
    monkeypatch.setattr(companies, "resolve", fake_resolve)
    assert companies.candidates("Acme Robotics, Inc.") == ["acmerobotics", "acme-robotics", "acme", "acmeroboticsinc", "acmeroboticshq"]
    async with client as c:
        r = (await c.post("/api/companies/resolve", json={"name": "Acme Robotics, Inc."})).json()
        assert r["boards"] == [{"kind": "greenhouse", "slug": "acmerobotics", "jobs": 2},
                               {"kind": "recruitee", "slug": "acme-robotics", "jobs": 1}] and not r["cached"]
        n = len(calls)
        assert (await c.post("/api/companies/resolve", json={"name": "acme robotics"})).json()["cached"]
        assert len(calls) == n
        assert (await c.post("/api/companies/resolve", json={"name": "Stripe"})).json()["boards"][0]["slug"] == "stripe"


# ---------- more ATS sources ----------
def _sr(r):
    if r.url.path.endswith("/postings"):
        return httpx.Response(200, json={"content": [{"id": "743", "name": "Data Engineer", "releasedDate": RECENT,
                                                      "location": {"city": "London", "country": "gb", "remote": False},
                                                      "company": {"name": "SR Co"}, "typeOfEmployment": {"label": "Full-time"}}]})
    return httpx.Response(200, json={"jobAd": {"sections": {"jobDescription": {"text": "<p>Build pipelines</p>"},
                                                            "qualifications": {"text": "<ul><li>Python</li></ul>"}}}})


ATS_FIXTURES = {
    "api.smartrecruiters.com": lambda r: _sr(r),
    "apply.workable.com": lambda r: httpx.Response(200, json={"name": "Wk Co", "jobs": [{"title": "Data Engineer", "shortcode": "AB1",
        "url": "https://apply.workable.com/wk/j/AB1", "city": "Berlin", "country": "Germany", "description": "<p>SQL</p>",
        "published_on": RECENT[:10], "telecommuting": True}]}),
    "acme.recruitee.com": lambda r: httpx.Response(200, json={"offers": [{"id": 9, "title": "Data Engineer", "careers_url": "https://acme.recruitee.com/o/de",
        "location": "Amsterdam", "description": "<p>Pipelines</p>", "requirements": "<ul><li>Spark</li></ul>", "published_at": RECENT}]}),
    "acme.jobs.personio.de": lambda r: httpx.Response(200, text="""<?xml version="1.0"?><workzag-jobs><position><id>55</id>
        <office>Munich</office><name>Data Engineer</name><jobDescriptions><jobDescription><name>Your profile</name>
        <value><![CDATA[<ul><li>Python</li></ul>]]></value></jobDescription></jobDescriptions><createdAt>2026-09-30T10:00:00+00:00</createdAt>
        <schedule>full-time</schedule></position></workzag-jobs>"""),
    "acme.teamtailor.com": lambda r: httpx.Response(200, text="""<?xml version="1.0"?><rss version="2.0"><channel><item>
        <title>Data Engineer</title><link>https://acme.teamtailor.com/jobs/123-data-engineer</link>
        <description>&lt;p&gt;Airflow&lt;/p&gt;</description><pubDate>Mon, 29 Sep 2026 10:00:00 +0000</pubDate></item></channel></rss>"""),
    "acme.wd5.myworkdayjobs.com": lambda r: httpx.Response(200, json={"total": 1, "jobPostings": [{"title": "Data Engineer",
        "externalPath": "/job/London/Data-Engineer_R123", "locationsText": "London", "postedOn": "Posted Today"}]})
        if r.method == "POST" else httpx.Response(200, json={"jobPostingInfo": {"jobDescription": "<p>Kafka</p>", "location": "London, UK",
                                                                               "startDate": RECENT[:10], "timeType": "Full time"}}),
    "data.usajobs.gov": lambda r: httpx.Response(200, json={"SearchResult": {"SearchResultItems": [{"MatchedObjectDescriptor": {
        "PositionID": "X-1", "PositionTitle": "IT Specialist (Data)", "OrganizationName": "Dept of Data",
        "PositionLocationDisplay": "Washington, DC", "PositionURI": "https://usajobs.gov/x1", "PublicationStartDate": RECENT[:10],
        "QualificationSummary": "SQL", "PositionRemuneration": [{"MinimumRange": "90000", "MaximumRange": "120000", "Description": "Per Year"}],
        "UserArea": {"Details": {"JobSummary": "Data work", "MajorDuties": ["Build pipelines"]}}}}]}})
        if r.headers.get("authorization-key") == "k-secret-1" else httpx.Response(401),
}


@pytest.mark.parametrize("sid,slug,company", [("smartrecruiters", "SRCo", "SR Co"), ("workable", "wk", "Wk Co"),
                                              ("recruitee", "acme", "Acme"), ("personio", "acme", "Acme"),
                                              ("teamtailor", "acme", "Acme"), ("workday", "acme/wd5/Careers", "Acme")])
async def test_new_ats_sources_parse(sid, slug, company):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: ATS_FIXTURES[r.url.host](r))) as c:
        jobs = await BY_ID[sid].fetch(JobQuery(title="data engineer", companies={sid: [slug]}), c)
    assert jobs and jobs[0].title == "Data Engineer" and jobs[0].company == company and jobs[0].source == sid
    assert jobs[0].description.strip() and jobs[0].url.startswith("https://")


async def test_workday_slug_validation_and_usajobs_key():
    from app.sources.base import SourceError
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: ATS_FIXTURES[r.url.host](r))) as c:
        with pytest.raises(SourceError, match="tenant/wd5"):
            await BY_ID["workday"].fetch(JobQuery(title="x", companies={"workday": ["acme"]}), c)
        with pytest.raises(SourceError, match="free API key"):
            await BY_ID["usajobs"].fetch(JobQuery(title="data"), c)
        jobs = await BY_ID["usajobs"].fetch(JobQuery(title="data", usajobs={"email": "a@b.co", "key": "k-secret-1"}), c)
        assert jobs[0].salary.startswith("$90000") and "Build pipelines" in jobs[0].description
        with pytest.raises(SourceError) as e:
            await BY_ID["usajobs"].fetch(JobQuery(title="data", usajobs={"email": "a@b.co", "key": "wrong-key-2"}), c)
        assert "wrong-key-2" not in str(e.value)


# ---------- market ----------
async def test_market_stats_from_stored_jobs(client, resume_pdf):  # noqa: F811
    async with client as c:
        await _analyzed(c, resume_pdf)                         # stores 3 "Data Engineer" postings
        m = (await c.get("/api/market", params={"title": "data engineer"})).json()
        assert m["jobs"] == 3 and m["top_skills"][0]["pct"] == 100 and m["remote_pct"] == 100
        assert m["median_years_asked"] == 3
        assert (await c.get("/api/market", params={"title": "pastry chef"})).json()["jobs"] == 0


def test_salary_parsing():
    from app.api.market import salary_point
    assert salary_point("$120k – $150k") == ("$", 135000.0)
    assert salary_point("£45 per hour") == ("£", 45 * 2080)
    assert salary_point("€5,000/month") == ("€", 60000.0)
    assert salary_point("competitive") is None and salary_point("$5") is None


# ---------- browser extension ----------
async def test_extension_token_score_save_and_cors(client, resume_pdf):  # noqa: F811
    async with client as c:
        await c.post("/api/resume/preview", files={"resume": ("cv.pdf", resume_pdf, "application/pdf")})
        tok = (await c.post("/api/ext/tokens")).json()["token"]
        page = {"title": "Data Engineer", "company": "PageCo", "url": "https://careers.pageco.com/1",
                "description": "Requirements\n- Python and SQL\n- Kubernetes\n- Active TS/SCI clearance required\n" + "x " * 30}
    async with _fresh() as ext:                              # the extension has no app cookie, only its token
        assert (await ext.post("/api/ext/score", json=page)).status_code == 401
        pre = await ext.options("/api/ext/score", headers={"Origin": "chrome-extension://abc", "Access-Control-Request-Method": "POST"})
        assert pre.status_code == 204 and pre.headers["access-control-allow-origin"] == "chrome-extension://abc"
        r = await ext.post("/api/ext/score", json=page, headers={"X-Ext-Token": tok, "Origin": "chrome-extension://abc"})
        assert r.status_code == 200 and r.headers["access-control-allow-origin"] == "chrome-extension://abc"
        s = r.json()
        assert "Kubernetes" in s["missing_required"] and any(g["label"] == "security clearance" and g["status"] == "fail" for g in s["gates"])
        saved = (await ext.post("/api/ext/save", json={**page, "score": s["score"]}, headers={"X-Ext-Token": tok})).json()
        assert saved["source"] == "extension"
        other = await ext.post("/api/ext/score", json=page, headers={"X-Ext-Token": tok, "Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in other.headers                   # only extension origins get CORS
    async with _fresh() as c2:
        c2.cookies = c.cookies                                  # same browser as the app session
        assert (await c2.get("/api/tracker")).json()["items"][0]["company"] == "PageCo"
        await c2.delete("/api/ext/tokens")
    async with _fresh() as ext:
        assert (await ext.post("/api/ext/score", json=page, headers={"X-Ext-Token": tok})).status_code == 401


# ---------- ops ----------
async def test_metrics_and_token(client, monkeypatch):  # noqa: F811
    metrics.reset()
    async with client as c:
        await c.get("/api/health")
        text = (await c.get("/metrics")).text
        assert 'cvm_http_requests_total{method="GET",route="/api/health",status="200"} 1' in text
        assert "cvm_jobs_stored" in text
        monkeypatch.setenv("METRICS_TOKEN", "m-token-123")
        assert (await c.get("/metrics")).status_code == 401
        assert (await c.get("/metrics", headers={"Authorization": "Bearer m-token-123"})).status_code == 200


async def test_canaries_record_health(monkeypatch):
    from app.sources.base import SourceError

    async def ok(q, client, *a):
        return [object()]

    async def broken(q, client, *a):
        raise SourceError("schema changed", "http")
    for sid in scheduler.CANARY_SOURCES:
        monkeypatch.setattr(BY_ID[sid], "fetch", ok if sid != "remoteok" else broken)
    out = await scheduler.canaries(client=httpx.AsyncClient())
    assert out["remotive"]["ok"] and not out["remoteok"]["ok"] and "schema" in out["remoteok"]["error"]
    assert db.kv_get("canary:remoteok")["ok"] is False


def test_json_logs_mask_keys():
    import logging
    from app.runtime.logs import JsonFormatter
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "using key sk-abcdef123456 and cvx_tokentoken1", None, None)
    out = json.loads(JsonFormatter().format(rec))
    assert "sk-abcdef" not in out["msg"] and "cvx_token" not in out["msg"] and out["level"] == "info"

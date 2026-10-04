"""Job fetching quality: title relevance, drop-reason funnel, detail enrichment, salary parsing, 500-job scale,
apply-strategy server checks, auto deep-check targeting, saved job links."""
import json

import httpx

from app import main
from app.agents import strategy
from app.jobmodel import Job
from app.sources import aggregate, enrich
from app.sources.base import JobQuery, Source
from tests.test_api import HDR, _analyzed, _mock_llm, client, wait_done  # noqa: F401  (fixture reuse)


def _rel(q, title, desc=""):
    return aggregate.relevance(Job(id="x", title=title, description=desc), aggregate.core_tokens(q))


def test_role_noun_guard_and_maths_synonym():
    assert _rel("Data Engineer", "Senior Data Engineer, Platform") == 1.0
    assert _rel("Data Engineer", "Engineering Manager, Data") < 0.75
    assert _rel("Registered Nurse", "Nurse Practitioner") < 0.75
    assert _rel("Machine Learning Engineer", "Machine Learning Scientist") < 0.75
    assert _rel("Math Teacher", "Secondary Maths Teacher") == 1.0
    assert _rel("Account Executive", "Executive Assistant") < 0.75


def _src(sid, jobs):
    async def fetch(q, client, progress=None):
        return [Job(**j) for j in jobs]
    return Source(sid, sid.title(), "search", "", fetch)


async def test_funnel_and_drop_reasons():
    a = _src("alpha", [{"id": "a1", "title": "Data Engineer", "company": "Acme", "location": "London"},
                       {"id": "a2", "title": "Sales Engineer", "company": "Acme", "location": "London"},
                       {"id": "a3", "title": "Data Engineer", "company": "Beta", "location": "Paris"},
                       {"id": "a4", "title": "Data Engineer", "company": "Gamma", "location": "London"}])
    b = _src("beta", [{"id": "b1", "title": "Data Engineer", "company": "Acme", "location": "London"}])     # duplicate of a1
    q = JobQuery(title="Data Engineer", location="London", count=1)
    jobs, stats, _ = await aggregate.run(q, [a, b], client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))))
    assert q.funnel == {"fetched": 5, "relevant": 4, "after_filters": 3, "unique": 2, "selected": 1}
    da = stats["alpha"]["dropped"]
    assert da["title"] == 1 and da["location"] == 1
    assert sum(s["dropped"].get("duplicate", 0) for s in stats.values()) == 1
    assert sum(s["dropped"].get("over_limit", 0) for s in stats.values()) == 1


def test_salary_from_text():
    assert enrich.salary_from_text("Pay: £45,000–55,000 a year") == "£45,000–55,000 a year"
    assert enrich.salary_from_text("CTC ₹12,00,000 per annum") == "₹12,00,000 per annum"
    assert enrich.salary_from_text("We have 5 offices and a $5 lunch voucher") == ""


async def test_enrichment_fills_thin_postings():
    ld = {"@context": "https://schema.org", "@type": "JobPosting", "title": "Data Engineer",
          "description": "<p>Requirements</p><ul><li>Python</li><li>SQL</li></ul>" + "<p>We build pipelines.</p>" * 40,
          "baseSalary": {"currency": "GBP", "value": {"minValue": 60000, "maxValue": 70000, "unitText": "YEAR"}}}
    page = f'<html><head><script type="application/ld+json">{json.dumps(ld)}</script></head><body>x</body></html>'
    seen = []

    def handler(r):
        seen.append(str(r.url))
        return httpx.Response(200, text=page)
    thin = Job(id="t", title="Data Engineer", url="https://careers.example.com/job/1", description="Short blurb.", extra={"truncated": True})
    blocked = Job(id="w", title="Data Engineer", url="https://wellfound.com/jobs/1", description="Short.")
    rich = Job(id="r", title="Data Engineer", url="https://careers.example.com/job/2", description="x" * 900, salary="£50k")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        n = await enrich.enrich([thin, blocked, rich], c)
    assert n == 1 and thin.extra.get("enriched") and "pipelines" in thin.description and "60000" in thin.salary
    assert seen == ["https://careers.example.com/job/1"]          # blocked host and rich job never fetched


def test_strategy_server_checks():
    facts = [{"job_id": "j1", "title": "DE", "company": "A", "score": 80, "qualifies": True, "gates_failed": []},
             {"job_id": "j2", "title": "DE2", "company": "B", "score": 75, "qualifies": False, "gates_failed": ["Work authorisation"]}]
    raw = strategy.Strategy(shortlist=[
        strategy.Pick(job_id="j1", priority=1, why="Scores 80%.", tailor_points=["x"], risk="Kafka"),
        strategy.Pick(job_id="j2", priority=1, why="Great.", tailor_points=[], risk="None"),
        strategy.Pick(job_id="ghost", priority=1, why="?", tailor_points=[], risk="")],
        skip=[strategy.Skip(job_id="ghost2", reason="no")], themes=["t"], next_steps=["Apply to 37 jobs"])
    out = strategy.check(raw, facts, "resume text")
    ids = [p["job_id"] for p in out["shortlist"]]
    assert ids == ["j1", "j2"] and out["dropped_ids"] == ["ghost", "ghost2"]
    j2 = out["shortlist"][1]
    assert j2["priority"] == 2 and j2["demoted"]                     # gated job can't be "apply now" without naming the gate
    assert "37" in out["unverified_numbers"]


async def test_max_jobs_is_500_and_deep_limit(client):  # noqa: F811
    async with client as c:
        assert (await c.get("/api/config")).json()["max_jobs"] == 500
        assert (await c.post("/api/search", json={"title": "data engineer", "count": 500})).status_code == 200
    assert main.DEEP_LIMIT == 100


async def test_strategy_and_auto_deep_stream(client, resume_pdf, monkeypatch):  # noqa: F811
    """AI advice, then the apply strategy, then auto deep-checks, all on one background run."""
    def handler(request):
        body = json.loads(request.content)
        fmt = ((body.get("response_format") or {}).get("json_schema") or {}).get("name")
        user = body["messages"][-1]["content"]
        if fmt == "Strategy":
            jobs = json.loads(user.split("<jobs>")[1].split("</jobs>")[0])
            out = {"shortlist": [{"job_id": jobs[0]["job_id"], "priority": 1, "why": "Top score.", "tailor_points": [], "risk": "Kafka"}],
                   "skip": [], "themes": ["Python"], "next_steps": ["Apply today"]}
        elif fmt in ("FixedAnswer", "OpenAnswer"):
            out = {"verdict": "possible", "summary": "ok", "assessments": []}
        elif fmt == "Answer":
            out = {"requirements": []}
        else:
            out = {"summary": "Solid.", "strengths": ["Python"], "improvements": ["Metrics"],
                   "skills_to_learn": [{"skill": "Kafka", "why": "w", "how": "h"}], "market_fit": "Competitive.",
                   "strongest_areas": ["pipelines"], "career_paths": [], "gap_plan": [{"week": 1, "focus": "Kafka", "outcome": "demo"}]}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(out)}}]})
    _mock_llm(monkeypatch, handler)
    from tests.test_api import _run_events
    async with client as c:
        body = await _analyzed(c, resume_pdf, HDR, use_ai="true", auto_deep="2")
        assert body["strategy"] == {"pending": True} and body["auto_deep"]["status"] == "queued"
        events = await _run_events(c, body["insights_run_id"])
        names = [e for e, _ in events]
        assert names.index("insight.ready") < names.index("strategy.ready") < names.index("deep.progress")
        assert names[-1] == "run.finished"
        a = (await c.get(f"/api/analysis/{body['analysis_id']}")).json()
    assert a["strategy"]["shortlist"][0]["priority"] == 1 and a["insights"]["market_fit"] == "Competitive."
    assert a["auto_deep"]["status"] == "done" and a["auto_deep"]["total"] == 2 and a["insights_run_id"] is None


# ---------- saved job links ----------
async def test_saved_links_lifecycle(client):  # noqa: F811
    async with client as c:
        r = (await c.post("/api/links", json={"text": "look at https://jobs.lever.co/acme/123, and http://localhost:8000/x\n"
                                                      "dup https://jobs.lever.co/acme/123 https://careers.example.com/job/1."})).json()
        assert r["added"] == 2 and r["rejected"][0]["url"].startswith("http://localhost")
        urls = [l["url"] for l in r["links"]]
        assert "https://careers.example.com/job/1" in urls                       # trailing "." trimmed
        assert (await c.post("/api/links", json={"text": "no links here"})).status_code == 422
        again = (await c.post("/api/links", json={"urls": ["https://jobs.lever.co/acme/123"]})).json()
        assert again["added"] == 0 and again["duplicates"] == 1
        one = r["links"][0]["id"]
        assert (await c.delete(f"/api/links/{one}")).status_code == 200
        assert len((await c.get("/api/links")).json()) == 1
        await c.delete("/api/links")
        assert (await c.get("/api/links")).json() == []


async def test_search_updates_saved_link_status(client, monkeypatch):  # noqa: F811
    from app.sources import urlimport
    ld = {"@context": "https://schema.org", "@type": "JobPosting", "title": "Data Engineer", "hiringOrganization": {"name": "Acme"},
          "description": "<p>Requirements</p><ul><li>Python and SQL</li></ul>" + "<p>more text</p>" * 30}
    page = f'<html><head><script type="application/ld+json">{json.dumps(ld)}</script></head><body>x</body></html>'

    async def fake_safe_get(client, url, headers=None):
        class F:  # noqa: N801
            status = 200 if "good" in url else 404
            text = page
        return F()
    monkeypatch.setattr(urlimport, "safe_get", fake_safe_get)
    async with client as c:
        await c.post("/api/links", json={"urls": ["https://careers.example.com/good", "https://careers.example.com/bad"]})
        sid = (await c.post("/api/search", json={"title": "data engineer", "sources": ["urls"], "count": 5,
                                                 "urls": ["https://careers.example.com/good", "https://careers.example.com/bad"]})).json()["search_id"]
        await wait_done(c, sid)
        links = {l["url"]: l for l in (await c.get("/api/links")).json()}
        s = (await c.get(f"/api/search/{sid}")).json()
    assert links["https://careers.example.com/good"]["status"] == "ok" and links["https://careers.example.com/good"]["company"] == "Acme"
    assert links["https://careers.example.com/bad"]["status"] == "failed" and "404" in links["https://careers.example.com/bad"]["message"]
    assert s["funnel"]["fetched"] == 1 and s["funnel"]["selected"] == 1

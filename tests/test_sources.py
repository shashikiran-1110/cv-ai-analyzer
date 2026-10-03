import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import linkedin
from app.jobmodel import Job
from app.sources import BY_ID, JobQuery, aggregate
from app.sources.base import SourceError
from app.sources.urlimport import parse_job_page
from app.textutil import html_to_text, parse_date

NOW = datetime.now(timezone.utc)
RECENT = (NOW - timedelta(hours=5)).isoformat()
OLD = (NOW - timedelta(days=40)).isoformat()
DESC = "<p>Requirements</p><ul><li>Python and SQL</li><li>3+ years of experience</li></ul>" + "<p>More text.</p>" * 5

FIXTURES = {
    "remotive.com": {"jobs": [
        {"id": 1, "url": "https://remotive.com/j/1", "title": "Senior Data Engineer", "company_name": "Acme",
         "candidate_required_location": "Worldwide", "publication_date": RECENT[:19], "description": DESC,
         "job_type": "full_time", "tags": ["python"], "salary": "$120k"},
        {"id": 2, "url": "https://remotive.com/j/2", "title": "Customer Support Lead", "company_name": "Zed",
         "candidate_required_location": "USA", "publication_date": RECENT[:19], "description": DESC}]},
    "remoteok.com": [{"legal": "notice"},
        {"id": "9", "position": "Data Engineer", "company": "Globex", "location": "", "date": RECENT,
         "description": DESC, "tags": ["sql"], "url": "https://remoteok.com/remote-jobs/9", "salary_min": 90000, "salary_max": 120000},
        {"id": "10", "position": "Data Engineer", "company": "Old Co", "date": OLD, "description": DESC}],
    "www.arbeitnow.com": {"data": [{"slug": "de-berlin", "company_name": "Cobalt GmbH", "title": "Data Engineer (m/w/d)",
                                    "description": DESC, "remote": False, "url": "https://arbeitnow.com/x",
                                    "tags": [], "job_types": ["full time"], "location": "Berlin", "created_at": int(NOW.timestamp()) - 3600}],
                          "links": {"next": None}},
    "jobicy.com": {"jobs": [{"id": 5, "url": "https://jobicy.com/5", "jobTitle": "Data Engineer", "companyName": "Initech",
                             "jobGeo": "Europe", "jobType": ["full-time"], "pubDate": RECENT[:19].replace("T", " "),
                             "jobDescription": DESC, "jobLevel": "Senior"}]},
    "himalayas.app": {"jobs": [{"title": "Data Engineer", "companyName": "Hooli", "locationRestrictions": ["United Kingdom"],
                                "description": DESC, "pubDate": int(NOW.timestamp()), "applicationLink": "https://h/1",
                                "guid": "g1", "employmentType": "Full Time", "seniority": ["Mid-level"], "categories": ["Data"]}]},
    "www.themuse.com": {"results": [{"id": 77, "name": "Data Engineer", "contents": DESC, "publication_date": RECENT,
                                     "locations": [{"name": "London, United Kingdom"}], "levels": [{"name": "Mid Level"}],
                                     "company": {"name": "Muse Co"}, "refs": {"landing_page": "https://themuse.com/j/77"}}]},
    "boards-api.greenhouse.io": {"jobs": [{"id": 11, "title": "Data Engineer", "location": {"name": "London"},
                                           "absolute_url": "https://boards.greenhouse.io/stripe/jobs/11",
                                           "updated_at": RECENT, "content": "&lt;p&gt;Requirements&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Python&lt;/li&gt;&lt;/ul&gt;"},
                                          {"id": 12, "title": "Account Executive", "location": {"name": "London"},
                                           "absolute_url": "https://x", "content": "sales"}]},
    "api.lever.co": [{"id": "abc", "text": "Data Engineer", "categories": {"location": "London", "commitment": "Full-time"},
                      "descriptionPlain": "Build pipelines.", "lists": [{"text": "Requirements", "content": "<li>Spark</li>"}],
                      "hostedUrl": "https://jobs.lever.co/acme/abc", "createdAt": int(NOW.timestamp() * 1000), "workplaceType": "hybrid"}],
    "api.ashbyhq.com": {"jobs": [{"id": "z1", "title": "Data Engineer", "location": "Remote - UK", "isRemote": True,
                                  "descriptionPlain": "Requirements\n- Python", "publishedAt": RECENT, "jobUrl": "https://jobs.ashbyhq.com/ramp/z1",
                                  "employmentType": "FullTime"}]},
    "api.adzuna.com": {"results": [{"id": "a1", "title": "<strong>Data</strong> Engineer", "description": "Python SQL…",
                                    "company": {"display_name": "Adz Ltd"}, "location": {"display_name": "London, UK"},
                                    "created": RECENT, "redirect_url": "https://adzuna/a1", "salary_min": 60000, "contract_time": "full_time"}]},
}


def handler_for(seen):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        host = request.url.host
        data = FIXTURES.get(host)
        if host == "api.lever.co" and "missing" in request.url.path:
            return httpx.Response(404)
        if data is None:
            return httpx.Response(404)
        return httpx.Response(200, json=data)
    return handler


@pytest.fixture
def client_and_seen():
    seen = []
    return httpx.AsyncClient(transport=httpx.MockTransport(handler_for(seen))), seen


Q = JobQuery(title="Data Engineer", location="London", count=50, hours=24 * 7,
             companies={"greenhouse": ["stripe"], "lever": ["acme"], "ashby": ["ramp"]},
             adzuna={"app_id": "id1", "app_key": "key1", "country": "gb"})


@pytest.mark.parametrize("sid,expect_title,expect_company", [
    ("remotive", "Senior Data Engineer", "Acme"), ("remoteok", "Data Engineer", "Globex"),
    ("arbeitnow", "Data Engineer (m/w/d)", "Cobalt GmbH"), ("jobicy", "Data Engineer", "Initech"),
    ("himalayas", "Data Engineer", "Hooli"), ("themuse", "Data Engineer", "Muse Co"),
    ("greenhouse", "Data Engineer", "Stripe"), ("lever", "Data Engineer", "Acme"),
    ("ashby", "Data Engineer", "Ramp"), ("adzuna", "Data Engineer", "Adz Ltd"),
])
async def test_each_source_parses(client_and_seen, sid, expect_title, expect_company):
    client, seen = client_and_seen
    async with client:
        jobs = await BY_ID[sid].fetch(Q, client)
    j = jobs[0]
    assert j.title == expect_title and j.company == expect_company
    assert j.id.startswith(sid) and j.source == sid
    assert j.url.startswith("https://")


async def test_greenhouse_unescapes_html_and_adzuna_sends_params(client_and_seen):
    client, seen = client_and_seen
    async with client:
        gh = await BY_ID["greenhouse"].fetch(Q, client)
        await BY_ID["adzuna"].fetch(Q, client)
    assert "• Python" in gh[0].description and "<" not in gh[0].description
    az = [r for r in seen if r.url.host == "api.adzuna.com"][0]
    assert az.url.params["what"] == "Data Engineer" and az.url.params["where"] == "London"
    assert az.url.params["max_days_old"] == "7" and "/gb/search/1" in az.url.path


async def test_config_errors():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))) as c:
        with pytest.raises(SourceError, match="company slug"):
            await BY_ID["greenhouse"].fetch(JobQuery(title="x"), c)
        with pytest.raises(SourceError, match="App ID"):
            await BY_ID["adzuna"].fetch(JobQuery(title="x"), c)
        with pytest.raises(SourceError, match="Invalid company"):
            await BY_ID["lever"].fetch(JobQuery(title="x", companies={"lever": ["../etc"]}), c)


async def test_partial_company_failure_is_a_warning(client_and_seen):
    client, _ = client_and_seen
    async with client:
        jobs = await BY_ID["lever"].fetch(JobQuery(title="x", companies={"lever": ["acme", "missing"]}), client)
    assert jobs and "missing" in " ".join(jobs[0].extra["_warnings"])


async def test_network_block_message():
    def boom(request):
        raise httpx.ConnectError("blocked")
    async with httpx.AsyncClient(transport=httpx.MockTransport(boom)) as c:
        with pytest.raises(SourceError) as e:
            await BY_ID["remotive"].fetch(Q, c)
    assert e.value.kind == "network" and "remotive.com" in str(e.value)


async def test_aggregate_filters_dedupes_and_isolates_failures(monkeypatch):
    async def fake_li(title, location, count, hours=None, on_progress=None, client=None, **kw):
        await on_progress("details", 1, 1)
        return [Job(id="1", title="Data Engineer", company="Globex Inc.", location="London", description="x" * 2000)]
    monkeypatch.setattr(linkedin, "search_jobs", fake_li)

    def handler(request):
        if request.url.host == "jobicy.com":
            raise httpx.ConnectError("blocked")
        return handler_for([])(request)

    srcs = [BY_ID[s] for s in ("linkedin", "remotive", "remoteok", "arbeitnow", "jobicy", "greenhouse", "themuse")]
    updates = []

    async def upd(stats):
        updates.append({k: v["status"] for k, v in stats.items()})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        jobs, stats, warnings = await aggregate.run(Q, srcs, upd, client=c)
    titles = {(j.source, j.title, j.company) for j in jobs}
    assert stats["jobicy"]["status"] == "error" and "jobicy.com" in stats["jobicy"]["message"]
    assert ("remotive", "Customer Support Lead", "Zed") not in titles          # irrelevant title dropped
    assert not any(j.company == "Old Co" for j in jobs)                        # older than time range
    assert not any(j.company == "Cobalt GmbH" for j in jobs)                   # Berlin != London
    assert not any(j.title == "Account Executive" for j in jobs)               # greenhouse irrelevant role
    globex = [j for j in jobs if "Globex" in j.company]
    assert len(globex) == 1 and set(globex[0].sources) == {"linkedin", "remoteok"}   # deduped across sources
    assert globex[0].source == "linkedin" and len(globex[0].description) >= 2000
    assert any(j.source == "remotive" for j in jobs) and any(j.source == "themuse" for j in jobs)
    assert updates[-1]["linkedin"] == "done"


def test_relevance_and_location_rules():
    core = aggregate.core_tokens("Senior Python Developer")
    assert core == ["python", "engineer"]
    assert aggregate.relevance(Job(id="1", title="Backend Engineer (Python)"), core) == 1.0
    assert aggregate.relevance(Job(id="1", title="Python Data Analyst"), core) < 0.75
    assert aggregate.core_tokens("Front-End Dev") == ["frontend", "engineer"]
    q = JobQuery(title="x", location="London")
    assert aggregate.location_ok(Job(id="1", title="t", location="London, UK"), q)
    assert aggregate.location_ok(Job(id="1", title="t", location="Remote - Europe", remote=True), q)
    assert aggregate.location_ok(Job(id="1", title="t", location="Worldwide", remote=True), q)
    assert not aggregate.location_ok(Job(id="1", title="t", location="USA only", remote=True), q)
    assert not aggregate.location_ok(Job(id="1", title="t", location="Paris"), q)
    ok, why = aggregate.filters_ok(Job(id="1", title="Senior Data Engineer"), JobQuery(title="x", experience=["entry"]))
    assert not ok and why == "experience"
    ok, why = aggregate.filters_ok(Job(id="1", title="t", employment_type="Contract"), JobQuery(title="x", job_types=["full_time"]))
    assert not ok and why == "job type"


def test_pick_round_robin():
    jobs = [(1.0 - i * 0.01, Job(id=f"l{i}", title="t", source="linkedin")) for i in range(10)]
    jobs += [(0.5, Job(id="r1", title="t", source="remotive")), (0.4, Job(id="r2", title="t", source="remotive"))]
    picked = aggregate.pick(jobs, 4)
    assert [j.source for j in picked].count("remotive") == 2


def test_jsonld_import_and_fallback():
    html = """<html><head><script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Organization"},
      {"@type":"JobPosting","title":"Data Engineer","description":"&lt;p&gt;Build pipelines&lt;/p&gt;",
       "hiringOrganization":{"@type":"Organization","name":"Acme"},"datePosted":"2026-09-30",
       "jobLocation":[{"address":{"addressLocality":"London","addressCountry":"GB"}}],
       "employmentType":["FULL_TIME"],"jobLocationType":"TELECOMMUTE",
       "baseSalary":{"currency":"GBP","value":{"minValue":70000,"maxValue":90000,"unitText":"YEAR"}}}]}</script></head><body></body></html>"""
    j = parse_job_page(html, "https://wellfound.com/jobs/123-data-engineer")
    assert j.title == "Data Engineer" and j.company == "Acme" and "London, GB" in j.location and j.remote
    assert "Build pipelines" in j.description and "70000" in j.salary and j.posted.startswith("2026-09-30")
    plain = "<html><head><title>Ops Engineer</title></head><body><main>" + "<p>We need ops skills.</p>" * 30 + "</main></body></html>"
    f = parse_job_page(plain, "https://careers.example.com/1")
    assert f.title == "Ops Engineer" and f.extra.get("unstructured")
    assert parse_job_page("<html><body>nothing</body></html>", "https://x") is None


async def test_url_import_wellfound_blocked_message():
    def handler(request):
        return httpx.Response(403, text="<html>captcha</html>")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(SourceError) as e:
            await BY_ID["urls"].fetch(JobQuery(title="x", urls=["https://wellfound.com/jobs/1-x"]), c)
    assert "Wellfound blocked" in str(e.value) and "Paste" in str(e.value)


def test_text_helpers():
    assert html_to_text("<ul><li>a</li><li>b</li></ul>") == "• a\n• b"
    assert html_to_text("plain  text") == "plain text"
    assert parse_date(1700000000).startswith("2023-11-14")
    assert parse_date(1700000000000).startswith("2023-11-14")
    assert parse_date("2024-01-02 10:00:00").startswith("2024-01-02T10:00")
    assert parse_date("garbage") == "" and parse_date(None) == ""


def test_location_country_awareness():
    q = JobQuery(title="x", location="London")
    assert aggregate.location_ok(Job(id="1", title="t", location="United Kingdom", remote=True), q)
    assert aggregate.location_ok(Job(id="1", title="t", location="Remote (UK only)", remote=True), q)
    assert not aggregate.location_ok(Job(id="1", title="t", location="United States", remote=True), q)
    assert not aggregate.location_ok(Job(id="1", title="t", location="Ukraine", remote=True), q)   # "uk" is a whole word
    assert aggregate.location_ok(Job(id="1", title="t", location="India", remote=True), JobQuery(title="x", location="Bengaluru"))


async def test_strict_title_matching_applies_to_linkedin(monkeypatch):
    async def fake_li(title, location, count, hours=None, on_progress=None, client=None, **kw):
        return [Job(id="1", title="Data Engineer", description="x" * 100), Job(id="2", title="Frontend Engineer", description="react " * 30)]
    monkeypatch.setattr(linkedin, "search_jobs", fake_li)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))) as c:
        strict, _, _ = await aggregate.run(JobQuery(title="Data Engineer"), [BY_ID["linkedin"]], client=c)
        loose, _, _ = await aggregate.run(JobQuery(title="Data Engineer", strict=False), [BY_ID["linkedin"]], client=c)
    assert [j.title for j in strict] == ["Data Engineer"]
    assert {j.title for j in loose} == {"Data Engineer", "Frontend Engineer"}


async def test_url_jobs_are_never_filtered_and_counted():
    page = ('<script type="application/ld+json">{"@type":"JobPosting","title":"Barista","description":"Make coffee daily '
            'for our customers and keep the bar clean.","hiringOrganization":{"name":"Cafe"}}</script>')
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=page))) as c:
        jobs, stats, _ = await aggregate.run(JobQuery(title="Data Engineer", location="London", urls=["https://cafe.example/j/1"]),
                                             [BY_ID["urls"]], client=c)
    assert [j.title for j in jobs] == ["Barista"] and stats["urls"]["selected"] == 1


async def test_adzuna_error_redaction_keeps_message_readable():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401))) as c:
        with pytest.raises(SourceError) as e:
            await BY_ID["adzuna"].fetch(JobQuery(title="x", adzuna={"app_id": "wrong", "app_key": "k", "country": "gb"}), c)
    assert "valid key" in str(e.value) and "***" not in str(e.value)
    def echo(request):
        return httpx.Response(500, text=f"bad key {request.url.params['app_key']}")
    async with httpx.AsyncClient(transport=httpx.MockTransport(echo)) as c:
        with pytest.raises(SourceError) as e:
            await BY_ID["adzuna"].fetch(JobQuery(title="x", adzuna={"app_id": "id12345", "app_key": "secretkey123", "country": "gb"}), c)
    assert "secretkey123" not in str(e.value)

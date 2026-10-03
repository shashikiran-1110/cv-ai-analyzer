"""Phase 3: resume parser + corrections, profile API, LLM requirement extractor."""
import json
from datetime import date

import httpx
from httpx import ASGITransport, AsyncClient

from app import main, matcher
from app.storage import db
from app.understanding import requirements as rx
from app.understanding import resume_parse as rp
from tests.test_api import HDR, _analyzed, _mock_llm, client  # noqa: F401  (fixture reuse)

CV = """Jane Doe
Senior Data Engineer
jane@example.com | +1 555 123 4567

Experience
Senior Data Engineer, Acme Analytics, Jan 2021 - Present
- Built streaming pipelines in Python and Kafka processing 2TB/day
- Cut warehouse cost by 35% with dbt and Snowflake
Acme Corp — Data Engineer
Mar 2019 - Dec 2020
- Built ETL jobs in Python and SQL on AWS

Education
MSc in Computer Science, Example University, 2017 - 2018

Skills
Python, SQL, Kafka, Docker
"""
TODAY = date(2026, 10, 1)


def test_parse_roles_bullets_skills_education():
    p = rp.parse(CV, TODAY)
    assert [(r["id"], r["title"], r["company"], r["start"], r["end"]) for r in p["roles"]] == [
        ("r1", "Senior Data Engineer", "Acme Analytics", "2021-01", "present"),
        ("r2", "Data Engineer", "Acme Corp", "2019-03", "2020-12")]
    assert [b["id"] for b in p["roles"][0]["bullets"]] == ["b1", "b2"]
    assert p["roles"][0]["bullets"][1]["metrics"]                       # "35%" counted as a quantified result
    sk = {s["name"]: s for s in p["skills"]}
    assert sk["Python"]["strength"] == "strong" and sk["Docker"]["source"] == "skills_list"
    assert sk["Docker"]["strength"] == "weak"
    assert p["education_level"] == "Master's" and p["education"][0]["institution"] == "Example University"
    assert "Jane" not in p["headline"]                                  # identity stripped


def test_formatting_check_flags():
    p = rp.parse(CV, TODAY)
    checks = {c["label"]: c for c in rp.formatting_check(CV, p)}
    assert checks["Standard section headings"]["ok"] and checks["Contact details present"]["ok"]
    assert checks["Dated roles (month and year)"]["ok"]
    assert not checks["Length"]["ok"]                                   # short sample


def test_corrections_override_parser_and_feed_matcher():
    corr = {"roles": {"r2": {"ignore": True}}, "skills_add": ["kubernetes"], "skills_remove": ["Docker"], "degree": "PhD"}
    p = rp.apply_corrections(rp.parse(CV, TODAY), corr)
    assert p["roles"][1]["ignore"] and p["education_level"] == "PhD"
    names = {s["name"] for s in p["skills"]}
    assert "Kubernetes" in names and "Docker" not in names
    prof = matcher.ResumeProfile.build(CV, 6, corrections=corr)
    assert "Kubernetes" in prof.skills and "Docker" not in prof.skills and prof.education == "PhD"
    assert prof.years < 6                                               # the ignored role no longer counts
    over = matcher.ResumeProfile.build(CV, 6, corrections={"years_override": 2})
    assert over.years == 2


def test_span_verification():
    units = rx._units("Requirements\n- 5+ years of Python experience\n- Degree in CS or similar. Fluent German.")
    assert rx.span_verified("5+ years of Python experience", units)
    assert rx.span_verified("Fluent German", units)
    assert not rx.span_verified("Kubernetes certification", units)
    assert rx.span_verified("Python", units) and not rx.span_verified("Kafka", units)   # bare skills: must be named
    assert not rx.span_verified("Teamwork", units)


async def test_profile_api_owner_and_corrections_rescore(client, resume_pdf):  # noqa: F811
    async with client as c:
        a = await _analyzed(c, resume_pdf)
        rid, aid = a["resume_id"], a["analysis_id"]
        prof = (await c.get(f"/api/profiles/{rid}")).json()
        assert prof["parsed"]["roles"] and prof["formatting"] and prof["corrections"] == {}
        before = {g["skill"] for g in a["summary"]["skill_gaps"]}
        assert "Kubernetes" in before
        r = await c.patch(f"/api/profiles/{rid}", json={"skills_add": ["Kubernetes"], "roles": {"r1": {"title": "Lead"}}})
        assert r.status_code == 200 and r.json()["profile"]["roles"][0]["title"] == "Lead"
        assert (await c.patch(f"/api/profiles/{rid}", json={"degree": "Wizard"})).status_code == 422
        rs = (await c.post(f"/api/analysis/{aid}/rescore", json={"extra_skills": []})).json()
        assert "Kubernetes" not in {g["skill"] for g in rs["summary"]["skill_gaps"]}
        # a new analysis of the same resume keeps the corrections
        again = await _analyzed(c, resume_pdf)
        assert "Kubernetes" not in {g["skill"] for g in again["summary"]["skill_gaps"]}
    other = AsyncClient(transport=ASGITransport(app=main.app), base_url="http://t")
    async with other as o:
        assert (await o.get(f"/api/profiles/{rid}")).status_code == 404       # different owner cookie
        assert (await o.get("/api/profiles/" + "x" * 31 + "!")).status_code == 404


async def test_extract_endpoint_verifies_spans_and_persists(client, resume_pdf, monkeypatch):  # noqa: F811
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        items = [{"text": t, "importance": imp, "kind": "skill", "years": 0} for t, imp in
                 [("Python and SQL", "must"), ("AWS and Docker", "must"), ("Kubernetes", "nice"),
                  ("10 years of Rust in production", "must")]]                  # last one isn't in the posting
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"requirements": items})}}]})

    _mock_llm(monkeypatch, handler)
    async with client as c:
        a = await _analyzed(c, resume_pdf)
        ids = [j["id"] for j in a["jobs"]]
        assert (await c.post(f"/api/analysis/{a['analysis_id']}/extract", json={"job_ids": ids})).status_code == 401
        r = await c.post(f"/api/analysis/{a['analysis_id']}/extract", json={"job_ids": ids}, headers=HDR)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["extracted"] == 3 and body["using_ai_requirements"] == 3
        texts = [q["text"] for q in body["jobs"][0]["requirements"]]
        assert texts == ["Python and SQL", "AWS and Docker", "Kubernetes"]
        assert next(q for q in body["jobs"][0]["requirements"] if q["text"] == "Kubernetes")["preferred"]
        n = calls["n"]
        await c.post(f"/api/analysis/{a['analysis_id']}/extract", json={"job_ids": ids}, headers=HDR)
        assert calls["n"] == n                                              # already current: no new AI calls
    with db.engine().connect() as conn:
        feats = json.loads(conn.execute(db.select(db.jobs.c.features).where(db.jobs.c.id == ids[0])).scalar())
    assert feats["requirements_meta"]["dropped"] == ["10 years of Rust in production"]


async def test_costs_and_deep_estimate(client, resume_pdf, monkeypatch):  # noqa: F811
    monkeypatch.setenv("LLM_PRICES", json.dumps({"gpt-5.6-luna": [1.0, 4.0, 0.1, 0]}))
    async with client as c:
        a = await _analyzed(c, resume_pdf)
        aid = a["analysis_id"]
        assert (await c.get(f"/api/analysis/{aid}/deep-estimate?n=2")).json()["estimate_usd"] is None   # no key
        e = (await c.get(f"/api/analysis/{aid}/deep-estimate?n=2", headers=HDR)).json()
        assert e["calls"] == 2 and e["estimate_usd"] > 0
        spend = (await c.get(f"/api/analysis/{aid}/costs")).json()
        assert spend["calls"] == 0 and spend["cost_usd"] == 0

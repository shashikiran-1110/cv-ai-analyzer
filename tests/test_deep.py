"""Deep Verifier v2 (ROADMAP §8.4): fixed requirement list, verified + relevant quotes, per-requirement combination."""
import json

import httpx

from app import deepmatch, matcher
from tests.test_api import HDR, _analyzed, _mock_llm, client  # noqa: F401  (fixture reuse)

RESUME = "Built ETL pipelines in Python and SQL on AWS; orchestrated with Airflow.\nLed a team of 4 engineers.\nAcme, Jan 2019 - Present"
NORM = deepmatch._norm(RESUME)


def test_evidence_found_and_relevant():
    assert deepmatch.evidence_in_resume("Built ETL pipelines in Python and SQL on AWS", NORM)
    assert deepmatch.evidence_in_resume("built etl pipelines in python and sql on aws;", NORM)
    assert not deepmatch.evidence_in_resume("Led a team of 40 engineers across 3 continents", NORM)
    assert deepmatch.evidence_relevant("Built ETL pipelines in Python and SQL", "Strong Python")
    assert not deepmatch.evidence_relevant("Led a team of 4 engineers.", "Experience with Kafka")
    assert deepmatch.evidence_relevant("Acme, Jan 2019 - Present", "3+ years of experience")       # duration requirement
    assert not deepmatch.evidence_relevant("Led a team of 4 engineers.", "3+ years of experience")


def test_judge_rules_d10():
    j = deepmatch._judge("met", "Ran Kubernetes clusters at scale", "Kubernetes", NORM)
    assert j["ai_status"] == "partial" and not j["verified"] and "not found" in j["flag"]
    j = deepmatch._judge("partial", "", "Kafka", NORM)
    assert j["ai_status"] == "missing" and not j["verified"] and j["flag"] == "no resume evidence given"
    j = deepmatch._judge("met", "Led a team of 4 engineers.", "Experience with Kafka", NORM)
    assert j["ai_status"] == "partial" and "doesn't relate" in j["flag"]
    j = deepmatch._judge("met", "orchestrated with Airflow", "Airflow orchestration", NORM)
    assert j["ai_status"] == "met" and j["verified"] and j["evidence"]


def _scored(reqs):
    rows = [{"id": f"r{i}", "text": t, "preferred": p, "coverage": c, "missing": [],
             "status": "met" if c >= .75 else "partial" if c >= .35 else "missing"} for i, (t, p, c) in enumerate(reqs, 1)]
    comps = {"skills": 80, "requirements": round(100 * matcher.requirement_coverage(rows)), "role": 100, "experience": 100, "semantic": 50}
    score = matcher.total_from({k: v / 100 for k, v in comps.items()})
    return {"score": score, "components": comps, "requirements": rows, "penalty": 0.0, "capped": False}


def test_combine_uses_ai_only_where_verified():
    scored = _scored([("Airflow orchestration", False, 0.0), ("Python", False, 1.0), ("Kafka", False, 0.0)])
    stored = {"job_id": "j", "mode": "fixed", "verdict": "possible", "summary": "", "provider": "openai", "model": "m",
              "judgments": {
                  "r1": {"text": "Airflow orchestration", "preferred": False, "note": "", **deepmatch._judge("met", "orchestrated with Airflow", "Airflow orchestration", NORM)},
                  "r2": {"text": "Python", "preferred": False, "note": "", **deepmatch._judge("missing", "", "Python", NORM)},
                  "r3": {"text": "Kafka", "preferred": False, "note": "", **deepmatch._judge("met", "Expert in Kafka streams", "Kafka", NORM)}}}
    d = deepmatch.combine(scored, stored)
    rows = {r["requirement"]: r for r in d["requirements"]}
    assert rows["Airflow orchestration"]["source"] == "ai" and rows["Airflow orchestration"]["final_status"] == "met"
    assert rows["Python"]["source"] == "rules" and rows["Python"]["final_status"] == "met" and rows["Python"]["disagree"]
    assert rows["Kafka"]["source"] == "rules" and rows["Kafka"]["final_status"] == "missing" and rows["Kafka"]["flag"]
    assert d["requirements_component"] == round(100 * 2 / 3) and d["final_score"] > d["det_score"]
    expected = matcher.total_from({**{k: v / 100 for k, v in scored["components"].items()}, "requirements": 2 / 3})
    assert d["final_score"] == expected                    # the engine's formula, not a 50/50 blend


def test_d10_partial_everywhere_without_evidence_earns_nothing():
    scored = _scored([("Python", False, 0.0), ("Kafka", False, 0.0)])
    stored = {"job_id": "j", "mode": "fixed", "verdict": "", "summary": "", "provider": "o", "model": "m",
              "judgments": {f"r{i}": {"text": t, "preferred": False, "note": "", **deepmatch._judge("partial", "", t, NORM)}
                            for i, t in enumerate(["Python", "Kafka"], 1)}}
    d = deepmatch.combine(scored, stored)
    assert d["final_score"] == d["det_score"] and d["verified"] == 0 and d["unverified_claims"] == 2


async def test_deep_endpoint_judges_the_engines_requirements(client, resume_pdf, monkeypatch):  # noqa: F811
    seen = {}

    def handler(request):
        body = json.loads(request.content)
        prompt = body["messages"][1]["content"]
        seen["prompt"] = prompt
        seen["system"] = body["messages"][0]["content"]
        seen["format"] = body.get("response_format")
        ids = [l.split("]")[0].split("[")[1] for l in prompt.splitlines() if l.startswith("- [r")]
        seen["ids"] = ids
        answer = {"verdict": "strong", "summary": "Good fit.", "assessments": [
            {"id": ids[0], "status": "met", "evidence": "Data engineer with 6 years of experience building data pipelines", "note": "ok"},
            {"id": ids[1], "status": "met", "evidence": "Expert in Python and SQL for 10 years at Google", "note": "invented"},
            {"id": ids[2], "status": "partial", "evidence": "", "note": "no quote"}]}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer)}}]})

    _mock_llm(monkeypatch, handler)
    desc = ("Requirements\n- 3+ years of experience building data pipelines\n- Strong Python and SQL skills\n"
            "- Hands-on experience with AWS and Docker\n" + "We are a friendly team. " * 6)
    async with client as c:
        sid = (await c.post("/api/search/manual", json={"jobs": [{"title": "Data Engineer", "company": "Acme",
                                                                   "description": desc}]})).json()["search_id"]
        a = (await c.post("/api/analyze", data={"search_id": sid},
                          files={"resume": ("cv.pdf", resume_pdf, "application/pdf")})).json()
        job = a["jobs"][0]
        aid, jid = a["analysis_id"], job["id"]
        assert len(job["requirements"]) >= 3     # (a trailing blurb is also picked up: tracked as Phase 1 finding F2)
        assert (await c.post(f"/api/analysis/{aid}/deep/{jid}")).status_code == 401
        r = await c.post(f"/api/analysis/{aid}/deep/{jid}", headers=HDR)
        assert r.status_code == 200, r.text
        d = r.json()["deep"]
    assert seen["ids"] == [q["id"] for q in job["requirements"]]                       # D11: same list
    assert seen["format"]["type"] == "json_schema" and seen["format"]["json_schema"]["strict"] is True
    assert "<resume>" in seen["system"] and "<resume>" not in seen["prompt"]          # resume is the cached prefix
    assert all(q["text"] in seen["prompt"] for q in job["requirements"])
    rows = d["requirements"]
    assert rows[0]["verified"] and rows[0]["source"] == "ai" and rows[0]["evidence"].startswith("Data engineer")
    assert rows[1]["ai_status"] == "partial" and rows[1]["flag"] and rows[1]["source"] == "rules"
    assert rows[2]["ai_status"] == "missing" and rows[2]["flag"] == "no resume evidence given"     # D10
    assert d["mode"] == "fixed" and d["unverified_claims"] == 2
    scored = next(j for j in r.json()["jobs"] if j["id"] == jid)
    assert scored["score"] == d["final_score"] and scored["score_det"] == d["det_score"]


async def test_deep_survives_rescore_and_open_mode(client, resume_pdf, monkeypatch):  # noqa: F811
    def handler(request):
        prompt = json.loads(request.content)["messages"][1]["content"]
        if "- [r" in prompt:
            ids = [l.split("]")[0].split("[")[1] for l in prompt.splitlines() if l.startswith("- [r")]
            ans = {"verdict": "stretch", "summary": "s",
                   "assessments": [{"id": i, "status": "missing", "evidence": "", "note": ""} for i in ids]}
        else:
            ans = {"verdict": "possible", "summary": "s",
                   "assessments": [{"requirement": "Python", "importance": "must", "status": "met",
                                    "evidence": "Built ETL pipelines in Python and SQL on AWS", "note": ""}]}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(ans)}}]})

    _mock_llm(monkeypatch, handler)
    async with client as c:
        a = await _analyzed(c, resume_pdf)
        aid, jid = a["analysis_id"], a["jobs"][0]["id"]
        await c.post(f"/api/analysis/{aid}/deep/{jid}", headers=HDR)
        rs = (await c.post(f"/api/analysis/{aid}/rescore", json={"extra_skills": ["Kubernetes"]})).json()
        j = next(x for x in rs["jobs"] if x["id"] == jid)
        assert j["deep"] and j["score"] == j["deep"]["final_score"] == j["score_det"]   # AI 'missing' can't lower rules

    from app.main import ANALYSES
    from app.deepmatch import assess
    from app.llm import LLMConfig
    out = await assess(LLMConfig("openai", "sk-secret-123", "m"), {"id": "x", "title": "T", "description": "short"},
                       {"score": 40, "requirements": []}, "Built ETL pipelines in Python and SQL on AWS")
    assert out["mode"] == "open" and out["judgments"]["ai1"]["verified"]
    assert ANALYSES is not None


async def test_deep_endpoint_bad_json(client, resume_pdf, monkeypatch):  # noqa: F811
    _mock_llm(monkeypatch, lambda req: httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]}))
    async with client as c:
        a = await _analyzed(c, resume_pdf)
        r = await c.post(f"/api/analysis/{a['analysis_id']}/deep/{a['jobs'][0]['id']}", headers=HDR)
    assert r.status_code == 502 and "wrong format" in r.json()["detail"]      # after one repair attempt

import json

import httpx

from app import deepmatch, llm
from tests.test_api import HDR, _analyzed, _mock_llm, client  # noqa: F401  (fixture reuse)


def test_evidence_verification():
    resume = deepmatch._norm("Built ETL pipelines in Python and SQL on AWS; orchestrated with Airflow.\nLed a team of 4 engineers.")
    assert deepmatch.evidence_in_resume("Built ETL pipelines in Python and SQL on AWS", resume)
    assert deepmatch.evidence_in_resume("built etl pipelines in python and sql on aws;", resume)      # case/punct
    assert not deepmatch.evidence_in_resume("Led a team of 40 engineers across 3 continents", resume)  # fabricated
    assert not deepmatch.evidence_in_resume("Kubernetes", resume)
    assert not deepmatch.evidence_in_resume("", resume)


def test_score_and_blend():
    reqs = [{"importance": "must", "status": "met"}, {"importance": "must", "status": "partial"},
            {"importance": "nice", "status": "missing"}]
    assert deepmatch.score_from(reqs) == round(100 * 1.5 / 2.5)
    assert deepmatch.blend(80, 60) == 70


async def test_deep_endpoint_downgrades_unverified_and_blends(client, resume_pdf, monkeypatch):  # noqa: F811
    answer = {"verdict": "strong", "summary": "Good fit.", "requirements": [
        {"requirement": "Python and SQL", "importance": "must", "status": "met",
         "evidence": "Built ETL pipelines in Python and SQL on AWS", "note": "Clear."},
        {"requirement": "Kubernetes", "importance": "must", "status": "met",
         "evidence": "Ran Kubernetes clusters at scale for 5 years", "note": "Invented."},
        {"requirement": "Terraform", "importance": "nice", "status": "missing", "evidence": "", "note": "Not shown."}]}

    def handler(request):
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        assert "<resume>" in body["messages"][1]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer)}}]})

    _mock_llm(monkeypatch, handler)
    async with client as c:
        a = await _analyzed(c, resume_pdf)
        aid, jid = a["analysis_id"], a["jobs"][0]["id"]
        assert (await c.post(f"/api/analysis/{aid}/deep/{jid}")).status_code == 401     # needs a key
        r = await c.post(f"/api/analysis/{aid}/deep/{jid}", headers=HDR)
        assert r.status_code == 200, r.text
        d = r.json()["deep"]
        reqs = {x["requirement"]: x for x in d["requirements"]}
        assert reqs["Python and SQL"]["verified"] and reqs["Python and SQL"]["status"] == "met"
        assert reqs["Kubernetes"]["status"] == "partial" and not reqs["Kubernetes"]["verified"]
        assert reqs["Kubernetes"]["flag"] and reqs["Kubernetes"]["claimed_evidence"].startswith("Ran Kubernetes")
        assert d["unverified_claims"] == 1
        assert d["ai_score"] == round(100 * (1 + 0.5) / 2.5)
        job = next(j for j in r.json()["jobs"] if j["id"] == jid)
        assert job["deep"]["final_score"] == job["score"] == deepmatch.blend(job["score_det"], d["ai_score"])
        # blended score survives a what-if rescore
        rs = (await c.post(f"/api/analysis/{aid}/rescore", json={"extra_skills": ["Kubernetes"]})).json()
        j2 = next(j for j in rs["jobs"] if j["id"] == jid)
        assert j2["deep"] and j2["score"] == deepmatch.blend(j2["score_det"], d["ai_score"])


async def test_deep_endpoint_bad_json(client, resume_pdf, monkeypatch):  # noqa: F811
    _mock_llm(monkeypatch, lambda req: httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]}))
    async with client as c:
        a = await _analyzed(c, resume_pdf)
        r = await c.post(f"/api/analysis/{a['analysis_id']}/deep/{a['jobs'][0]['id']}", headers=HDR)
    assert r.status_code == 502 and "unreadable" in r.json()["detail"]

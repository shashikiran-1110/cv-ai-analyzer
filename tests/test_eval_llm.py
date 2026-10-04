"""LLM evaluation system: record/replay, the adversarial mock, defense invariants, Eval Studio API, feedback."""
import json

import httpx
import pytest

from app import deepmatch, insights, llm
from app.ai import gateway, guard
from eval import run as R
from eval.llm import mockmodel
from eval.llm.runner import run_suite
from tests.test_api import HDR, _analyzed, _mock_llm, client  # noqa: F401  (fixture reuse)


# ---------- gateway: record / replay / isolation ----------
async def test_record_then_replay_roundtrip(tmp_path, monkeypatch):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}], "usage": {"prompt_tokens": 5, "completion_tokens": 1}})
    _mock_llm(monkeypatch, handler)
    cfg = llm.LLMConfig("openai", "sk-x-123456", "gpt-5.6-luna")
    tok = gateway.EVAL_TAGS.set({"owner": "eval", "run_id": "r1", "mode": "record", "cassette_dir": str(tmp_path)})
    try:
        assert await gateway.complete(cfg, gateway.Call(agent="t", use_cache=False), "sys", [{"role": "user", "content": "q"}]) == "hello"
    finally:
        gateway.EVAL_TAGS.reset(tok)
    assert len(calls) == 1 and len(list(tmp_path.glob("*.json"))) == 1
    tok = gateway.EVAL_TAGS.set({"owner": "eval", "run_id": "r2", "mode": "replay", "cassette_dir": str(tmp_path)})
    try:   # replay: same answer, no network
        assert await gateway.complete(cfg, gateway.Call(agent="t", use_cache=False), "sys", [{"role": "user", "content": "q"}]) == "hello"
        assert len(calls) == 1
        with pytest.raises(gateway.CassetteMiss):     # a changed prompt is a loud miss, never a silent live call
            await gateway.complete(cfg, gateway.Call(agent="t", use_cache=False), "sys", [{"role": "user", "content": "other"}])
    finally:
        gateway.EVAL_TAGS.reset(tok)


async def test_eval_mode_is_request_local(monkeypatch):
    """An eval run in the server must never redirect other users' calls to the mock."""
    mockmodel.install()
    seen = []

    def handler(request):
        seen.append(1)
        return httpx.Response(200, json={"choices": [{"message": {"content": "real"}}]})
    _mock_llm(monkeypatch, handler)
    cfg = llm.LLMConfig("openai", "sk-x-123456", "gpt-5.6-luna")
    out = await gateway.complete(cfg, gateway.Call(agent="t", use_cache=False), "sys", [{"role": "user", "content": "q"}])
    assert out == "real" and seen == [1]


# ---------- defenses hold against the adversarial mock ----------
@pytest.mark.parametrize("suite,metric", [("llm_deep_verify", "unsupported_quote_accepted"), ("llm_safety", "attack_success_defended"),
                                          ("llm_tailoring", "unverifiable_in_accepted"), ("llm_interview", "new_numbers_unflagged")])
def test_defense_invariants_in_mock_mode(suite, metric):
    r = run_suite(suite, "mock", persist=False)
    assert r["metrics"][metric] == 0, r["failures"]
    assert r["metrics"]["errors"] == 0


def test_mock_model_actually_misbehaves():
    """The mock is only useful if it attacks: it must comply with injections and fabricate quotes."""
    r = run_suite("llm_safety", "mock", persist=False)
    assert r["metrics"]["raw_compliance_rate"] == 1.0
    d = run_suite("llm_deep_verify", "mock", persist=False)
    assert d["metrics"]["hallucinated_quote_rate"] > 0 and d["metrics"]["raw_overcredit_rate"] > 0


def test_evidence_relevance_suite():
    m = R.suite_evidence()["metrics"]
    assert m["accuracy"] == 1.0 and m["false_accepts"] == 0


def test_bls_does_not_prove_acls():
    assert not deepmatch.evidence_relevant("Basic Life Support (BLS) certified", "ACLS certification")
    assert deepmatch.evidence_relevant("Basic Life Support (BLS) certified", "Current BLS certification")


def test_prompt_leak_filter():
    assert guard.echoes_instructions("My instructions: " + insights.SYSTEM[:200], insights.SYSTEM)
    assert not guard.echoes_instructions("You qualify for 9 of 30 jobs; Kafka is your biggest gap.", insights.SYSTEM)


def test_cli_runs_llm_suites_and_checks(tmp_path, monkeypatch):
    assert R.main(["--suite", "llm_safety,evidence", "--mode", "mock", "--check", "--no-persist", "--out", str(tmp_path / "r.md")]) == 0
    assert "llm_safety" in (tmp_path / "r.md").read_text()


# ---------- history, feedback, Eval Studio ----------
async def test_reports_history_and_delete(client, resume_pdf):  # noqa: F811
    async with client as c:
        a = await _analyzed(c, resume_pdf)
        rows = (await c.get("/api/analyses")).json()
        assert rows and rows[0]["analysis_id"] == a["analysis_id"] and rows[0]["job_count"] == len(a["jobs"])
        assert (await c.delete(f"/api/analysis/{a['analysis_id']}")).status_code == 200
        assert (await c.get("/api/analyses")).json() == []


async def test_requirement_correction_rescores(client, resume_pdf):  # noqa: F811
    async with client as c:
        a = await _analyzed(c, resume_pdf)
        job = next(j for j in a["jobs"] if any(r["status"] != "met" for r in j["requirements"]))
        req = next(r for r in job["requirements"] if r["status"] != "met")
        r = await c.post("/api/feedback", json={"kind": "requirement", "analysis_id": a["analysis_id"], "job_id": job["id"],
                                                "item_id": req["text"], "rating": -1, "correction": {"status": "met"}})
        assert r.status_code == 200, r.text
        j2 = next(j for j in r.json()["jobs"] if j["id"] == job["id"])
        row = next(x for x in j2["requirements"] if x["text"] == req["text"])
        assert row["status"] == "met" and row["how"] == "your correction"
        assert j2["score"] >= job["score"]
        # survives a reload of the analysis
        again = (await c.get(f"/api/analysis/{a['analysis_id']}")).json()
        assert next(x for x in next(j for j in again["jobs"] if j["id"] == job["id"])["requirements"] if x["text"] == req["text"])["status"] == "met"
        assert (await c.post("/api/feedback", json={"kind": "insights", "rating": 0})).status_code == 422
        summ = (await c.get("/api/feedback/summary")).json()
        assert summ[0]["kind"] == "requirement" and summ[0]["corrections"] == 1


async def test_eval_studio_api(client, tmp_path, monkeypatch):  # noqa: F811
    from app.api import evals
    monkeypatch.setattr(evals, "MATCH", tmp_path)
    monkeypatch.setattr(evals, "LLM_DATA", tmp_path)
    (tmp_path / "queue.jsonl").write_text("".join(json.dumps({"id": f"p{i}", "resume": "r", "job_title": "t", "job_description": "d", "prelabels": []}) + "\n" for i in range(3)))
    async with client as c:
        run = (await c.post("/api/eval/run", json={"suite": "llm_safety", "mode": "mock"})).json()
        assert run["metrics"]["attack_success_defended"] == 0 and run["cases_detail"]
        assert (await c.post("/api/eval/run", json={"suite": "llm_safety", "mode": "live"})).status_code == 422   # never spends from the UI
        ov = (await c.get("/api/eval/overview")).json()
        assert any(h["key"] == "llm_safety.attack_success_defended" and h["value"] == 0 for h in ov["headline"])
        assert (await c.get(f"/api/eval/runs/{run['id']}")).status_code == 200
        q = (await c.get("/api/eval/labels/queue")).json()
        assert q["stats"]["queue"] == 3
        s1 = (await c.post("/api/eval/labels", json={"id": "p0", "label": "strong", "reviewer": "A"})).json()
        assert s1["reviewed"] == 1 and s1["queue"] == 2
        # a second reviewer on the same pair enables Cohen's kappa
        await c.post("/api/eval/labels", json={"id": "p1", "label": "no", "reviewer": "A"})
        q2 = [json.loads(l) for l in (tmp_path / "queue.jsonl").read_text().splitlines()]
        for it in q2:
            it.pop("done", None)
        (tmp_path / "queue.jsonl").write_text("".join(json.dumps(x) + "\n" for x in q2))
        await c.post("/api/eval/labels", json={"id": "p0", "label": "strong", "reviewer": "B"})
        s = (await c.post("/api/eval/labels", json={"id": "p1", "label": "no", "reviewer": "B"})).json()
        assert s["double_labelled"] == 2 and s["kappa"] == 1.0
        assert (await c.post("/api/eval/labels", json={"id": "p0", "label": "no", "reviewer": "B"})).status_code in (404, 409)


async def test_eval_admins_gate(client, monkeypatch):  # noqa: F811
    monkeypatch.setenv("EVAL_ADMINS", "boss@example.com")
    async with client as c:
        assert (await c.get("/api/eval/overview")).status_code == 403

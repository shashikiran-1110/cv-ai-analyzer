"""ROADMAP Phase 3: LLM gateway — structured output, repair, retries, breaker, caching, cost logging, budgets."""
import json

import httpx
import pytest
from pydantic import BaseModel

from app import llm
from app.ai import gateway
from app.storage import db

OPENAI = llm.LLMConfig("openai", "sk-test-123456", "gpt-5.6-luna")
CLAUDE = llm.LLMConfig("anthropic", "sk-ant-test-123456", "claude-sonnet-5-5")


class Answer(BaseModel):
    verdict: str
    items: list[str]


@pytest.fixture(autouse=True)
def _reset():
    gateway.reset_breakers()
    yield
    gateway.reset_breakers()


def _mock(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(llm, "_client", lambda: real(transport=httpx.MockTransport(handler)))


def _openai_reply(content, usage=None):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}],
                                     "usage": usage or {"prompt_tokens": 1000, "completion_tokens": 100,
                                                        "prompt_tokens_details": {"cached_tokens": 800}}})


def test_strict_schema_closes_objects_and_inlines_refs():
    class Inner(BaseModel):
        a: str

    class Outer(BaseModel):
        xs: list[Inner]
        n: int = 3
    s = gateway.strict_schema(Outer)
    assert "$defs" not in json.dumps(s) and s["additionalProperties"] is False and s["required"] == ["xs", "n"]
    assert s["properties"]["xs"]["items"]["additionalProperties"] is False and "default" not in json.dumps(s)


async def test_openai_structured_logs_usage_and_caches_result(monkeypatch):
    calls = []

    def handler(r):
        calls.append(json.loads(r.content))
        return _openai_reply(json.dumps({"verdict": "ok", "items": ["a"]}))
    _mock(monkeypatch, handler)
    call = gateway.Call(agent="t", owner="o1", analysis_id="a" * 32)
    out = await gateway.structured(OPENAI, call, "sys", "user", Answer, cacheable="<resume>R</resume>")
    assert out.items == ["a"]
    body = calls[0]
    assert body["response_format"]["type"] == "json_schema" and body["messages"][0]["content"].endswith("<resume>R</resume>")
    again = await gateway.structured(OPENAI, gateway.Call(agent="t", owner="o1", analysis_id="a" * 32), "sys", "user", Answer,
                                     cacheable="<resume>R</resume>")
    assert again.items == ["a"] and len(calls) == 1                        # result cache: no second paid call
    spend = db.llm_spend(analysis_id="a" * 32)
    assert spend["calls"] == 2 and spend["result_cache_hits"] == 1 and spend["cached_tokens"] == 800
    assert spend["cost_known"] is False                                     # no OpenAI price on file → unknown


async def test_anthropic_payload_cache_control_effort_and_cost(monkeypatch):
    seen = {}

    def handler(r):
        seen.update(json.loads(r.content))
        return httpx.Response(200, json={"content": [{"type": "thinking", "thinking": ""},
                                                     {"type": "text", "text": json.dumps({"verdict": "v", "items": []})}],
                                         "stop_reason": "end_turn",
                                         "usage": {"input_tokens": 200, "output_tokens": 50,
                                                   "cache_read_input_tokens": 3000, "cache_creation_input_tokens": 0}})
    _mock(monkeypatch, handler)
    out = await gateway.structured(CLAUDE, gateway.Call(agent="t", analysis_id="b" * 32, use_cache=False), "instructions",
                                   "job text", Answer, cacheable="<resume>R</resume>")
    assert out.verdict == "v"
    assert seen["system"][1] == {"type": "text", "text": "<resume>R</resume>", "cache_control": {"type": "ephemeral"}}
    assert seen["output_config"]["format"]["type"] == "json_schema" and seen["output_config"]["effort"] == "medium"
    assert "tool_choice" not in seen and seen["max_tokens"] >= 16000 and "thinking" not in seen
    expected = (200 * 2.0 + 50 * 10.0 + 3000 * 0.20) / 1e6
    assert db.llm_spend(analysis_id="b" * 32)["cost_usd"] == pytest.approx(expected)


async def test_repair_retry_then_success(monkeypatch):
    replies = iter([json.dumps({"verdict": "x"}), json.dumps({"verdict": "x", "items": ["fixed"]})])
    bodies = []

    def handler(r):
        bodies.append(json.loads(r.content))
        return _openai_reply(next(replies))
    _mock(monkeypatch, handler)
    out = await gateway.structured(OPENAI, gateway.Call(agent="t", use_cache=False), "s", "u", Answer)
    assert out.items == ["fixed"] and "did not match" in bodies[1]["messages"][-1]["content"]


async def test_schema_rejected_falls_back_to_json_mode(monkeypatch):
    bodies = []

    def handler(r):
        b = json.loads(r.content)
        bodies.append(b)
        if b.get("response_format", {}).get("type") == "json_schema":
            return httpx.Response(400, json={"error": {"message": "response_format json_schema not supported"}})
        return _openai_reply(json.dumps({"verdict": "ok", "items": []}))
    _mock(monkeypatch, handler)
    out = await gateway.structured(OPENAI, gateway.Call(agent="t", use_cache=False), "s", "u", Answer)
    assert out.verdict == "ok" and bodies[1]["response_format"] == {"type": "json_object"}


async def test_retries_on_overloaded_then_breaker_opens(monkeypatch):
    monkeypatch.setattr(gateway.asyncio, "sleep", _nosleep)
    n = []

    def overloaded(r):
        n.append(1)
        return httpx.Response(529, json={"error": {"type": "overloaded_error", "message": "Overloaded"}})
    _mock(monkeypatch, overloaded)
    with pytest.raises(llm.LLMError):
        await gateway.complete(CLAUDE, gateway.Call(agent="t", use_cache=False), "s", [{"role": "user", "content": "u"}])
    assert len(n) == 3                                                     # retried
    with pytest.raises(llm.LLMError):
        await gateway.complete(CLAUDE, gateway.Call(agent="t", use_cache=False), "s", [{"role": "user", "content": "u"}])
    with pytest.raises(llm.LLMError, match="pausing"):                     # 5+ failures → breaker open, no request
        await gateway.complete(CLAUDE, gateway.Call(agent="t", use_cache=False), "s", [{"role": "user", "content": "u"}])
    assert len(n) == 6


async def _nosleep(*a, **k):
    return None


async def test_no_retry_on_auth_error(monkeypatch):
    n = []
    _mock(monkeypatch, lambda r: (n.append(1), httpx.Response(401, json={"error": {"message": "bad key"}}))[1])
    with pytest.raises(llm.LLMError, match="rejected the API key"):
        await gateway.complete(OPENAI, gateway.Call(agent="t", use_cache=False), "s", [{"role": "user", "content": "u"}])
    assert len(n) == 1


async def test_stream_usage_logged_anthropic(monkeypatch):
    sse = "".join(f"event: x\ndata: {json.dumps(e)}\n\n" for e in [
        {"type": "message_start", "message": {"usage": {"input_tokens": 10, "cache_read_input_tokens": 500, "output_tokens": 1}}},
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi"}},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 7}}])
    _mock(monkeypatch, lambda r: httpx.Response(200, text=sse))
    out = [p async for p in gateway.stream(CLAUDE, gateway.Call(agent="chat", analysis_id="c" * 32), "s",
                                           [{"role": "user", "content": "u"}])]
    assert out == ["Hi"]
    sp = db.llm_spend(analysis_id="c" * 32)
    assert sp["output_tokens"] == 7 and sp["cached_tokens"] == 500 and sp["input_tokens"] == 10


async def test_daily_budget_applies_to_server_key_only(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_AI_PER_DAY_USD", "0.0001")
    db.log_llm_call(owner="o9", agent="x", provider="anthropic", model="claude-sonnet-5-5", key_source="server",
                    input_tokens=1, output_tokens=1, cached_tokens=0, cache_write_tokens=0, cost_usd=1.0,
                    latency_ms=1, status="ok", cache_hit=0)
    server = llm.LLMConfig("anthropic", "k" * 20, "claude-sonnet-5-5", "server")
    with pytest.raises(llm.LLMError, match="budget"):
        gateway.check_budget(server, gateway.Call(agent="x", owner="o9"))
    gateway.check_budget(CLAUDE, gateway.Call(agent="x", owner="o9"))          # user's own key: not blocked


def test_estimate_uses_cache_pricing():
    cfg = llm.LLMConfig("anthropic", "k" * 20, "claude-sonnet-5-5")
    one = gateway.estimate_cost(cfg, "standard", 40000, 900, 1, cached_chars=40000)
    ten = gateway.estimate_cost(cfg, "standard", 40000, 900, 10, cached_chars=40000)
    assert one and ten and ten < one * 10                                   # cached prefix makes later calls cheaper
    assert gateway.estimate_cost(OPENAI, "standard", 1000, 100) is None

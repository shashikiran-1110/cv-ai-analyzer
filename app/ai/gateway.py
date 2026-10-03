"""LLM gateway (ROADMAP §8.2): one place for every model call.

- Providers: OpenAI (chat completions) and Anthropic (Messages API), raw HTTP over the app's httpx client so the
  project stays provider-neutral (the user chooses the provider and key in the UI).
- Structured output: a Pydantic model → strict JSON schema → OpenAI `response_format: json_schema` /
  Anthropic `output_config.format` (forced tool use is rejected by current Claude models, so it is not used).
  The reply is validated; one repair retry with the validation error; a provider that rejects the schema format
  is retried once in plain-JSON mode.
- Retries with jittered backoff on 408/409/429/5xx/529, honouring `retry-after`; a per-provider circuit breaker.
- Prompt caching: stable content (instructions, then the resume) goes first; on Anthropic the cacheable system
  block carries `cache_control`; OpenAI caches long shared prefixes automatically. Usage reports cached tokens.
- Result cache keyed by (agent, prompt version, model, input hash) so identical work is never paid twice.
- Every call is logged to `llm_calls` (tokens, cached tokens, estimated cost, latency, status).
- Budgets: a daily USD cap per visitor applies when the *server's* key is used (a user's own key is theirs).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal, Optional, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .. import llm
from ..storage import db

log = logging.getLogger("ai.gateway")
T = TypeVar("T", bound=BaseModel)
Tier = Literal["fast", "standard", "frontier"]

# $ per million tokens: (input, output, cache read, cache write 5-min). Source: Anthropic pricing (2026-09).
# OpenAI prices vary by account/model; add them (or override any model) with LLM_PRICES='{"model": [in, out, read, write]}'.
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-fable-5-1": (10.0, 50.0, 0.25, 12.5), "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-opus-5": (5.0, 25.0, 0.50, 6.25), "claude-sonnet-5-5": (2.0, 10.0, 0.20, 2.5),
    "claude-sonnet-5": (2.0, 10.0, 0.20, 2.5), "claude-haiku-4-5": (1.0, 5.0, 0.10, 1.25),
}
TIER_DEFAULTS = {"anthropic": {"fast": "claude-haiku-4-5", "standard": "claude-sonnet-5-5", "frontier": "claude-opus-5-5"}}
EFFORT = {"fast": "low", "standard": "medium", "frontier": "high"}
RETRYABLE = {408, 409, 429, 500, 502, 503, 504, 529}
MAX_TOKENS = {"complete": 16000, "stream": 32000}   # adaptive thinking counts toward max_tokens on current Claude models


def prices() -> dict[str, tuple[float, float, float, float]]:
    p = dict(PRICES)
    try:
        p.update({k: tuple(v) for k, v in json.loads(os.getenv("LLM_PRICES", "{}")).items()})
    except (ValueError, TypeError):
        log.warning("LLM_PRICES is not valid JSON; ignored")
    return p


def cost_usd(model: str, inp: int, out: int, cache_read: int = 0, cache_write: int = 0) -> Optional[float]:
    pr = prices().get(model)
    if not pr:
        return None
    return round((inp * pr[0] + out * pr[1] + cache_read * pr[2] + cache_write * pr[3]) / 1e6, 6)


def model_for(cfg: llm.LLMConfig, tier: Tier) -> str:
    """The user's chosen model is used for every tier unless LLM_TIER_<TIER> is set (server-side override)."""
    return os.getenv(f"LLM_TIER_{tier.upper()}") or cfg.model


def _supports_effort(model: str) -> bool:
    m = model.lower()
    return m.startswith(("claude-opus-5", "claude-sonnet-5", "claude-fable-5", "claude-mythos-5", "claude-opus-4-8",
                         "claude-opus-4-7", "claude-opus-4-6", "claude-sonnet-4-6"))


# ---------- schema ----------
_DROP = {"title", "default", "examples", "minLength", "maxLength", "minItems", "maxItems", "minimum", "maximum",
         "exclusiveMinimum", "exclusiveMaximum", "pattern", "format", "uniqueItems"}


def strict_schema(model: type[BaseModel]) -> dict:
    """Pydantic schema → strict JSON schema: $refs inlined, every object closed with all properties required.
    Length/range constraints are dropped from the wire schema and enforced by Pydantic validation instead."""
    raw = model.model_json_schema()
    defs = raw.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].split("/")[-1]])
            if "allOf" in node and len(node["allOf"]) == 1:
                return walk(node["allOf"][0])
            out = {k: walk(v) for k, v in node.items() if k not in _DROP and k != "$defs"}
            if out.get("type") == "object" and "properties" in out:
                out["additionalProperties"] = False
                out["required"] = list(out["properties"])
            return out
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node
    return walk(raw)


# ---------- circuit breaker ----------
@dataclass
class Breaker:
    failures: int = 0
    open_until: float = 0.0


_breakers: dict[str, Breaker] = {}
BREAKER_THRESHOLD = 5
BREAKER_COOLDOWN = 60.0


def _breaker_check(provider: str) -> None:
    b = _breakers.get(provider)
    if b and b.open_until > time.monotonic():
        raise llm.LLMError(f"{provider} has been failing repeatedly; pausing AI calls for a minute.", 503)


def _breaker_record(provider: str, ok: bool) -> None:
    b = _breakers.setdefault(provider, Breaker())
    if ok:
        b.failures, b.open_until = 0, 0.0
    else:
        b.failures += 1
        if b.failures >= BREAKER_THRESHOLD:
            b.open_until = time.monotonic() + BREAKER_COOLDOWN


def reset_breakers() -> None:
    _breakers.clear()


# ---------- request building ----------
@dataclass
class Call:
    agent: str
    prompt_version: int = 1
    tier: Tier = "standard"
    owner: str = ""
    analysis_id: str = ""
    run_id: str = ""
    use_cache: bool = True
    cache_ttl: float = 30 * 86400
    budget_usd: Optional[float] = None       # per-call cap (estimate) when set
    extra: dict = field(default_factory=dict)


def _payload(cfg: llm.LLMConfig, model: str, system: str, cacheable: str, messages: list[dict], *, stream: bool,
             schema: Optional[dict], schema_name: str, tier: Tier, json_mode: bool, volatile: str = "") -> tuple[str, dict]:
    """Prompt layout, most stable first: instructions → cacheable (e.g. the resume) → volatile context → messages."""
    base = llm._base(cfg)
    if cfg.provider == "openai":
        sys_text = system + ("\n\n" + cacheable if cacheable else "") + ("\n\n" + volatile if volatile else "")
        payload: dict = {"model": model, "stream": stream, "messages": [{"role": "system", "content": sys_text}, *messages]}
        if stream:
            payload["stream_options"] = {"include_usage": True}
        if schema is not None:
            payload["response_format"] = {"type": "json_schema", "json_schema": {"name": schema_name, "schema": schema, "strict": True}}
        elif json_mode:
            payload["response_format"] = {"type": "json_object"}
        return f"{base}/chat/completions", payload
    sys_blocks: list[dict] = [{"type": "text", "text": system}]
    if cacheable:
        sys_blocks.append({"type": "text", "text": cacheable, "cache_control": {"type": "ephemeral"}})
    else:
        sys_blocks[0]["cache_control"] = {"type": "ephemeral"}
    if volatile:
        sys_blocks.append({"type": "text", "text": volatile})       # after the breakpoint: never invalidates the cache
    payload = {"model": model, "max_tokens": MAX_TOKENS["stream" if stream else "complete"], "system": sys_blocks,
               "messages": messages, "stream": stream}
    oc: dict = {}
    if _supports_effort(model):
        oc["effort"] = EFFORT[tier]
    if schema is not None:
        oc["format"] = {"type": "json_schema", "schema": schema}
    if oc:
        payload["output_config"] = oc
    return f"{base}/messages", payload


def _usage(provider: str, data: dict) -> dict:
    u = data.get("usage") or {}
    if provider == "openai":
        return {"input": int(u.get("prompt_tokens") or 0) - int((u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0),
                "output": int(u.get("completion_tokens") or 0),
                "cache_read": int((u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0), "cache_write": 0}
    return {"input": int(u.get("input_tokens") or 0), "output": int(u.get("output_tokens") or 0),
            "cache_read": int(u.get("cache_read_input_tokens") or 0), "cache_write": int(u.get("cache_creation_input_tokens") or 0)}


def _text(provider: str, data: dict) -> str:
    if provider == "openai":
        return (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    if data.get("stop_reason") == "refusal":
        raise llm.LLMError("The AI declined this request.", 422)
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def _log(call: Call, cfg: llm.LLMConfig, model: str, usage: dict, t0: float, status: str, cache_hit: bool = False) -> Optional[float]:
    c = cost_usd(model, usage.get("input", 0), usage.get("output", 0), usage.get("cache_read", 0), usage.get("cache_write", 0)) \
        if not cache_hit else 0.0
    try:
        db.log_llm_call(owner=call.owner, analysis_id=call.analysis_id, run_id=call.run_id, agent=call.agent,
                        provider=cfg.provider, model=model, key_source=cfg.source, input_tokens=usage.get("input", 0),
                        output_tokens=usage.get("output", 0), cached_tokens=usage.get("cache_read", 0),
                        cache_write_tokens=usage.get("cache_write", 0), cost_usd=c,
                        latency_ms=int((time.perf_counter() - t0) * 1000), status=status, cache_hit=int(cache_hit))
    except Exception:
        log.exception("could not log llm call")
    return c


def check_budget(cfg: llm.LLMConfig, call: Call) -> None:
    """Daily cap per visitor on the *server's* key (ROADMAP §8.2 budgets; §10.1 abuse of server key)."""
    if cfg.source != "server":
        return
    cap = float(os.getenv("RATE_LIMIT_AI_PER_DAY_USD", "2.00"))
    spent = db.llm_spend(owner=call.owner, since=time.time() - 86400)["cost_usd"]
    if cap > 0 and spent >= cap:
        raise llm.LLMError(f"Daily AI budget reached (${cap:.2f}). Add your own API key in AI settings to continue.", 429)


async def _post(cfg: llm.LLMConfig, url: str, payload: dict) -> dict:
    _breaker_check(cfg.provider)
    delay = 1.0
    last: Optional[llm.LLMError] = None
    for attempt in range(3):
        try:
            async with llm._client() as c:
                r = await c.post(url, headers=llm._headers(cfg), json=payload)
        except httpx.HTTPError as e:
            last = llm.LLMError(f"Couldn't reach the AI provider ({type(e).__name__}).")
        else:
            if r.status_code == 200:
                _breaker_record(cfg.provider, True)
                return r.json()
            err = llm._error_for(r.status_code, r.content, cfg)
            if r.status_code not in RETRYABLE:
                if r.status_code >= 500:
                    _breaker_record(cfg.provider, False)
                raise err
            last = err
            ra = r.headers.get("retry-after", "")
            if ra.replace(".", "", 1).isdigit():
                delay = min(float(ra), 20.0)
        _breaker_record(cfg.provider, False)
        if attempt < 2:
            await asyncio.sleep(delay + random.uniform(0, delay / 2))
            delay *= 2
    raise last or llm.LLMError("The AI provider failed.")


def _cache_key(call: Call, model: str, system: str, cacheable: str, messages: list[dict], schema: Optional[dict]) -> str:
    h = hashlib.sha256(json.dumps([call.agent, call.prompt_version, model, system, cacheable, messages, schema],
                                  sort_keys=True).encode()).hexdigest()
    return f"ai:{call.agent}:{h}"


async def complete(cfg: llm.LLMConfig, call: Call, system: str, messages: list[dict], *, cacheable: str = "",
                   json_mode: bool = False) -> str:
    """Plain text (or loose JSON) completion through the gateway."""
    return (await _complete(cfg, call, system, messages, cacheable=cacheable, schema=None, schema_name="", json_mode=json_mode))[0]


async def _complete(cfg, call: Call, system, messages, *, cacheable, schema, schema_name, json_mode) -> tuple[str, dict]:
    model = model_for(cfg, call.tier)
    key = _cache_key(call, model, system, cacheable, messages, schema) if call.use_cache else ""
    if key:
        hit = db.kv_get(key)
        if hit is not None:
            _log(call, cfg, model, {}, time.perf_counter(), "ok", cache_hit=True)
            return hit, {"cached_result": True}
    check_budget(cfg, call)
    url, payload = _payload(cfg, model, system, cacheable, messages, stream=False, schema=schema,
                            schema_name=schema_name, tier=call.tier, json_mode=json_mode)
    t0 = time.perf_counter()
    try:
        data = await _post(cfg, url, payload)
    except llm.LLMError as e:
        if schema is not None and e.status == 400:      # provider/model without schema support → plain JSON mode
            url, payload = _payload(cfg, model, system + "\nReply with JSON only.", cacheable, messages, stream=False,
                                    schema=None, schema_name="", tier=call.tier, json_mode=True)
            data = await _post(cfg, url, payload)
        else:
            _log(call, cfg, model, {}, t0, f"error:{e.status}")
            raise
    usage = _usage(cfg.provider, data)
    text = _text(cfg.provider, data)
    c = _log(call, cfg, model, usage, t0, "ok")
    if key:
        db.kv_set(key, text, call.cache_ttl)
    return text, {"usage": usage, "cost_usd": c, "model": model}


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        s, e = text.find("{"), text.rfind("}")
        if s >= 0 and e > s:
            return json.loads(text[s:e + 1])
        raise


async def structured(cfg: llm.LLMConfig, call: Call, system: str, user: str, schema_model: type[T], *,
                     cacheable: str = "") -> T:
    """Schema-validated output. One repair round-trip on invalid output, then a clear error."""
    schema = strict_schema(schema_model)
    messages = [{"role": "user", "content": user}]
    text, _ = await _complete(cfg, call, system, messages, cacheable=cacheable, schema=schema,
                              schema_name=schema_model.__name__, json_mode=True)
    try:
        return schema_model.model_validate(_parse_json(text))
    except (ValueError, ValidationError) as e:
        err = str(e)[:800]
    repair = messages + [{"role": "assistant", "content": text[:6000]},
                         {"role": "user", "content": f"That reply did not match the required JSON schema:\n{err}\n"
                                                     "Reply again with corrected JSON only."}]
    rcall = Call(**{**call.__dict__, "use_cache": False})
    text2, _ = await _complete(cfg, rcall, system, repair, cacheable=cacheable, schema=schema,
                               schema_name=schema_model.__name__, json_mode=True)
    try:
        out = schema_model.model_validate(_parse_json(text2))
    except (ValueError, ValidationError):
        raise llm.LLMError("The AI returned an answer in the wrong format twice. Try again.", 502)
    if call.use_cache:     # cache the repaired, valid answer under the original key
        db.kv_set(_cache_key(call, model_for(cfg, call.tier), system, cacheable, messages, schema), text2, call.cache_ttl)
    return out


async def stream(cfg: llm.LLMConfig, call: Call, system: str, messages: list[dict], *, cacheable: str = "",
                 volatile: str = "") -> AsyncIterator[str]:
    """Streaming text with usage logging at the end."""
    model = model_for(cfg, call.tier)
    check_budget(cfg, call)
    _breaker_check(cfg.provider)
    url, payload = _payload(cfg, model, system, cacheable, messages, stream=True, schema=None, schema_name="",
                            tier=call.tier, json_mode=False, volatile=volatile)
    usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    t0 = time.perf_counter()
    status = "ok"
    try:
        async with llm._client() as c:
            async with c.stream("POST", url, headers=llm._headers(cfg), json=payload) as r:
                if r.status_code != 200:
                    _breaker_record(cfg.provider, r.status_code < 500)
                    raise llm._error_for(r.status_code, await r.aread(), cfg)
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        evt = json.loads(raw)
                    except ValueError:
                        continue
                    if cfg.provider == "openai":
                        if evt.get("usage"):
                            usage = _usage("openai", evt)
                        for ch in evt.get("choices") or []:
                            piece = (ch.get("delta") or {}).get("content")
                            if piece:
                                yield piece
                    else:
                        t = evt.get("type")
                        if t == "message_start":
                            u = _usage("anthropic", evt.get("message") or {})
                            usage.update({k: v for k, v in u.items() if k != "output"})
                        elif t == "message_delta":
                            usage["output"] = int((evt.get("usage") or {}).get("output_tokens") or usage["output"])
                            if (evt.get("delta") or {}).get("stop_reason") == "refusal":
                                raise llm.LLMError("The AI declined this request.", 422)
                        elif t == "content_block_delta":
                            piece = (evt.get("delta") or {}).get("text")
                            if piece:
                                yield piece
                        elif t == "error":
                            raise llm.LLMError(llm._redact(str((evt.get("error") or {}).get("message", "stream error")), cfg))
        _breaker_record(cfg.provider, True)
    except llm.LLMError as e:
        status = f"error:{e.status}"
        raise
    except httpx.HTTPError as e:
        status = "error:network"
        raise llm.LLMError(f"Connection to the AI provider was interrupted ({type(e).__name__}).")
    finally:
        _log(call, cfg, model, usage, t0, status)


def estimate_cost(cfg: llm.LLMConfig, tier: Tier, input_chars: int, output_tokens: int, calls: int = 1,
                  cached_chars: int = 0) -> Optional[float]:
    """Rough pre-flight estimate (≈4 characters per token) shown before bulk AI actions."""
    model = model_for(cfg, tier)
    pr = prices().get(model)
    if not pr:
        return None
    first = cost_usd(model, input_chars // 4, output_tokens, 0, cached_chars // 4) or 0.0
    rest = cost_usd(model, (input_chars - cached_chars) // 4, output_tokens, cached_chars // 4, 0) or 0.0
    return round(first + rest * max(0, calls - 1), 4)

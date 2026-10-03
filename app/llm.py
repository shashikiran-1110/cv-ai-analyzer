"""Provider-agnostic LLM access (OpenAI + Anthropic) over plain httpx.

The API key comes from the browser (per-request headers) or, as a fallback, the server environment.
It is never stored, logged, or echoed back: every error message is passed through `_redact`.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import AsyncIterator, Mapping, Optional

import httpx

from . import config

ANTHROPIC_URL = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODELS = {"openai": config.OPENAI_MODEL, "anthropic": config.CLAUDE_MODEL}


class LLMError(Exception):
    """User-presentable LLM failure. `status` is the HTTP status to surface."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class LLMConfig:
    provider: str          # "openai" | "anthropic"
    api_key: str
    model: str
    source: str = "browser"  # or "server"

    def public(self) -> dict:
        return {"provider": self.provider, "model": self.model, "source": self.source}


def resolve(headers: Mapping[str, str]) -> Optional[LLMConfig]:
    """Build an LLMConfig from request headers, falling back to server env keys."""
    key = (headers.get("x-ai-key") or "").strip()
    provider = (headers.get("x-ai-provider") or "").strip().lower()
    model = (headers.get("x-ai-model") or "").strip()
    if key:
        if provider not in DEFAULT_MODELS:
            raise LLMError("Choose an AI provider (OpenAI or Anthropic).", 422)
        return LLMConfig(provider, key, model or DEFAULT_MODELS[provider], "browser")
    env = config.ai_provider()
    if env:
        envkey = os.environ["OPENAI_API_KEY" if env == "openai" else "ANTHROPIC_API_KEY"]
        return LLMConfig(env, envkey, model or DEFAULT_MODELS[env], "server")
    return None


def require(headers: Mapping[str, str]) -> LLMConfig:
    cfg = resolve(headers)
    if not cfg:
        raise LLMError("Add an AI API key in AI settings to use the assistant.", 401)
    return cfg


def _client() -> httpx.AsyncClient:  # indirection so tests can inject a MockTransport
    return httpx.AsyncClient(timeout=httpx.Timeout(90, connect=10))


def _redact(text: str, cfg: LLMConfig) -> str:
    return text.replace(cfg.api_key, "***") if len(cfg.api_key) >= 6 else text


def _base(cfg: LLMConfig) -> str:
    return config.OPENAI_BASE_URL.rstrip("/") if cfg.provider == "openai" else ANTHROPIC_URL


def _headers(cfg: LLMConfig) -> dict:
    if cfg.provider == "openai":
        return {"Authorization": f"Bearer {cfg.api_key}"}
    return {"x-api-key": cfg.api_key, "anthropic-version": ANTHROPIC_VERSION}


def _provider_message(resp_body: bytes, cfg: LLMConfig) -> str:
    try:
        err = json.loads(resp_body).get("error", {})
        msg = err.get("message") if isinstance(err, dict) else str(err)
    except (ValueError, AttributeError):
        msg = ""
    return _redact((msg or "")[:300], cfg)


def _error_for(status: int, body: bytes, cfg: LLMConfig) -> LLMError:
    detail = _provider_message(body, cfg)
    name = "OpenAI" if cfg.provider == "openai" else "Anthropic"
    if status == 401:
        return LLMError(f"{name} rejected the API key. Check that it's correct and active.", 401)
    if status == 403:
        return LLMError(f"{name} refused the request (permission denied). {detail}".strip(), 403)
    if status == 404:
        return LLMError(f"Model “{cfg.model}” was not found for this key. {detail}".strip(), 404)
    if status == 429:
        return LLMError(f"{name} rate limit or quota reached. {detail}".strip(), 429)
    if status == 400:
        return LLMError(f"{name} rejected the request: {detail or 'bad request'}", 400)
    return LLMError(f"{name} returned an error (HTTP {status}). {detail}".strip(), 502)


async def verify(cfg: LLMConfig) -> dict:
    """Cheap, token-free check: fetch the model's metadata. Distinguishes bad key from bad model."""
    url = f"{_base(cfg)}/models/{cfg.model}"
    try:
        async with _client() as c:
            r = await c.get(url, headers=_headers(cfg))
    except httpx.HTTPError as e:
        return {"ok": False, "message": f"Couldn't reach the provider ({type(e).__name__}). Check your network."}
    if r.status_code == 200:
        return {"ok": True, "message": f"Key verified. Model “{cfg.model}” is available.", **cfg.public()}
    if r.status_code == 403:  # restricted keys may not read model metadata but can still chat
        return {"ok": True, "warning": True, **cfg.public(),
                "message": "Key accepted, but it can't list models, so the model name couldn't be confirmed."}
    err = _error_for(r.status_code, r.content, cfg)
    return {"ok": False, "message": str(err)}


def _build(cfg: LLMConfig, system: str, messages: list[dict], *, stream: bool, json_mode: bool) -> tuple[str, dict]:
    if cfg.provider == "openai":
        payload: dict = {"model": cfg.model, "stream": stream,
                         "messages": [{"role": "system", "content": system}, *messages]}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return f"{_base(cfg)}/chat/completions", payload
    payload = {"model": cfg.model, "max_tokens": 4096, "system": system, "messages": messages, "stream": stream}
    return f"{_base(cfg)}/messages", payload


async def complete(cfg: LLMConfig, system: str, messages: list[dict], json_mode: bool = False) -> str:
    url, payload = _build(cfg, system, messages, stream=False, json_mode=json_mode)
    try:
        async with _client() as c:
            r = await c.post(url, headers=_headers(cfg), json=payload)
    except httpx.HTTPError as e:
        raise LLMError(f"Couldn't reach the AI provider ({type(e).__name__}).")
    if r.status_code != 200:
        raise _error_for(r.status_code, r.content, cfg)
    data = r.json()
    if cfg.provider == "openai":
        return data["choices"][0]["message"]["content"] or ""
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


async def stream(cfg: LLMConfig, system: str, messages: list[dict]) -> AsyncIterator[str]:
    url, payload = _build(cfg, system, messages, stream=True, json_mode=False)
    try:
        async with _client() as c:
            async with c.stream("POST", url, headers=_headers(cfg), json=payload) as r:
                if r.status_code != 200:
                    raise _error_for(r.status_code, await r.aread(), cfg)
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        return
                    try:
                        evt = json.loads(raw)
                    except ValueError:
                        continue
                    if cfg.provider == "openai":
                        for ch in evt.get("choices", []):
                            piece = (ch.get("delta") or {}).get("content")
                            if piece:
                                yield piece
                    else:
                        if evt.get("type") == "content_block_delta":
                            piece = (evt.get("delta") or {}).get("text")
                            if piece:
                                yield piece
                        elif evt.get("type") == "error":
                            raise LLMError(_redact(str(evt.get("error", {}).get("message", "stream error")), cfg))
    except httpx.HTTPError as e:
        raise LLMError(f"Connection to the AI provider was interrupted ({type(e).__name__}).")

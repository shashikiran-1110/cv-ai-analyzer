"""Small in-house agent loop (ROADMAP §8.10) on top of the gateway: provider-neutral, tool registry with Pydantic
argument schemas, step/budget limits, a trace per step, and pause/resume for `ask_user`.

Agents can only *propose*: tools never cause side effects outside the run (no sending, no saving to the user's
documents) without the user confirming in the UI (ROADMAP §8.9).
"""
from __future__ import annotations

import inspect
import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel, ValidationError

from .. import llm
from . import gateway, guard


@dataclass
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    fn: Callable[..., Any]                       # fn(args_model) -> JSON-able (sync or async)

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description, "schema": gateway.strict_schema(self.args)}


class AskUser(Exception):
    """Raised by a tool to pause the run until the user answers `question`."""

    def __init__(self, question: str):
        super().__init__(question)
        self.question = question


class Finish(Exception):
    def __init__(self, summary: str):
        super().__init__(summary)
        self.summary = summary


@dataclass
class Result:
    status: str                                  # done | needs_input | limit | error
    final: str = ""
    question: str = ""
    trace: list[dict] = field(default_factory=list)
    state: dict = field(default_factory=dict)    # what `resume` needs (messages + pending tool call)
    error: str = ""


def _tool_results(cfg: llm.LLMConfig, results: list[tuple[str, str, bool]]) -> list[dict]:
    if cfg.provider == "openai":
        return [{"role": "tool", "tool_call_id": cid, "content": out} for cid, out, _ in results]
    return [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": cid, "content": out, "is_error": err}
                                         for cid, out, err in results]}]


def _dump(x: Any, limit: int = 6000) -> str:
    s = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False, default=str)
    return s[:limit]


async def run(cfg: llm.LLMConfig, call: gateway.Call, system: str, user: str, tools: list[Tool], *,
              max_steps: int = 12, cacheable: str = "", on_step: Optional[Callable[[dict], Awaitable[None]]] = None,
              state: Optional[dict] = None, answer: Optional[str] = None) -> Result:
    """Run (or resume, with `state` + `answer`) an agent until it answers, asks the user, or hits a limit."""
    by_name = {t.name: t for t in tools}
    specs = [t.spec() for t in tools]
    trace: list[dict] = list((state or {}).get("trace") or [])
    if state:
        messages = state["messages"]
        pending = state.get("pending") or []      # tool calls of the paused turn: [(id, output|None)]
        results = [(cid, out if out is not None else _dump({"user_answer": answer or ""}), False) for cid, out in pending]
        messages += _tool_results(cfg, results)
        trace.append({"step": len(trace) + 1, "tool": "ask_user", "output": (answer or "")[:300], "kind": "answer"})
    else:
        messages = [{"role": "user", "content": user}]
    steps = sum(1 for t in trace if t.get("kind") == "model")
    while steps < max_steps:
        steps += 1
        t0 = time.perf_counter()
        res = await gateway.tool_step(cfg, call, system, messages, specs, cacheable=cacheable)
        messages.append(res["assistant"])
        step = {"step": len(trace) + 1, "kind": "model", "text": res["text"][:400],
                "tools": [c["name"] for c in res["tool_calls"]], "ms": round((time.perf_counter() - t0) * 1000)}
        trace.append(step)
        if on_step:
            await on_step(step)
        if not res["tool_calls"]:
            return Result("done", final=res["text"], trace=trace)
        results: list[tuple[str, Optional[str], bool]] = []
        question = ""
        final: Optional[str] = None
        for c in res["tool_calls"]:
            tool = by_name.get(c["name"])
            t1 = time.perf_counter()
            err = False
            if tool is None:
                out, err = _dump({"error": f"unknown tool {c['name']}"}), True
            else:
                try:
                    args = tool.args.model_validate(c["input"])
                    value = tool.fn(args)
                    if inspect.isawaitable(value):
                        value = await value
                    out = guard.sanitize_untrusted(_dump(value))
                except ValidationError as e:
                    out, err = _dump({"error": "invalid arguments", "detail": str(e)[:600]}), True
                except AskUser as q:
                    question, out = q.question, None
                except Finish as f:
                    final, out = f.summary, _dump({"ok": True})
            results.append((c["id"], out, err))
            st = {"step": len(trace) + 1, "kind": "tool", "tool": c["name"], "input": _dump(c["input"], 400),
                  "output": (out or "")[:400], "error": err, "ms": round((time.perf_counter() - t1) * 1000)}
            trace.append(st)
            if on_step:
                await on_step(st)
        if question:
            return Result("needs_input", question=question, trace=trace,
                          state={"messages": messages, "pending": [(cid, out) for cid, out, _ in results], "trace": trace})
        messages += _tool_results(cfg, [(cid, out or "", e) for cid, out, e in results])
        if final is not None:
            return Result("done", final=final, trace=trace)
    return Result("limit", final="Stopped after the step limit.", trace=trace)

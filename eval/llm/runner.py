"""Runs one LLM eval suite in a chosen mode and records the run.

Modes
- mock    scripted adversarial model (eval/llm/mockmodel.py): no key, no network, deterministic. Proves the
          server-side defenses (quote verification, claim guard, planner filter, number checks) hold. Quality
          numbers from mock runs are meaningless and are never compared with real-model baselines.
- record  call the real model and save every response as a cassette (eval/cassettes/<suite>/<provider>-<model>/).
- replay  re-run against saved cassettes: real-model behaviour, deterministic and free. Misses fail loudly.
- live    call the real model, save nothing.

Every run is stored in `eval_runs` / `eval_cases` (shown in Eval Studio) with cost from the LLM call log.
"""
from __future__ import annotations

import asyncio
import json
import os
import statistics
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import func, select

from app import llm
from app.ai import gateway
from app.storage import db

ROOT = Path(__file__).resolve().parents[1]
CASSETTES = ROOT / "cassettes"
MODES = ("mock", "record", "replay", "live")


@dataclass
class Ctx:
    suite: str
    mode: str
    cfg: llm.LLMConfig
    run_id: str
    judge: Optional[llm.LLMConfig] = None
    repeats: int = 1
    notes: list[str] = field(default_factory=list)


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-._" else "-" for c in s)[:80]


def cassette_dir(suite: str, cfg: llm.LLMConfig) -> Path:
    return CASSETTES / suite / _slug(f"{cfg.provider}-{cfg.model}")


def config_for(mode: str, suite: str, provider: str = "", model: str = "") -> llm.LLMConfig:
    if mode == "mock":
        return llm.LLMConfig("openai", "mock", model or "mock-adversarial", "eval")
    if mode == "replay":
        manifest = CASSETTES / suite / "manifest.json"
        if not model:
            if not manifest.exists():
                raise SystemExit(f"No cassettes recorded for {suite}. Record first: python -m eval.run --suite {suite} --mode record")
            m = json.loads(manifest.read_text())
            provider, model = m["provider"], m["model"]
        return llm.LLMConfig(provider or "openai", "replay", model, "eval")
    provider = (provider or os.getenv("AI_PROVIDER") or ("openai" if os.getenv("OPENAI_API_KEY") else "anthropic")).lower()
    key = os.getenv("AI_KEY") or os.getenv("OPENAI_API_KEY" if provider == "openai" else "ANTHROPIC_API_KEY") or ""
    if not key:
        raise SystemExit(f"Mode {mode} calls the real model: set OPENAI_API_KEY or ANTHROPIC_API_KEY (or AI_KEY + AI_PROVIDER).")
    return llm.LLMConfig(provider, key, model or os.getenv("AI_MODEL") or llm.DEFAULT_MODELS[provider], "eval")


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT.parent, capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


async def run_cases(ctx: Ctx, cases: list[dict], fn: Callable[[Ctx, dict], Awaitable[dict]], concurrency: int = 3) -> list[dict]:
    """Run fn over every case (× repeats). Each result: {case_id, repeat, passed, ms, detail..., error?}."""
    sem = asyncio.Semaphore(concurrency)

    async def one(case: dict, rep: int) -> dict:
        async with sem:
            gateway.EVAL_TAGS.set({"owner": "eval", "run_id": ctx.run_id, "salt": f"r{rep}" if ctx.repeats > 1 else "",
                                   "mode": "" if ctx.mode == "live" else ctx.mode, "cassette_dir": str(cassette_dir(ctx.suite, ctx.cfg))})
            t0 = time.perf_counter()
            try:
                out = await fn(ctx, case)
            except Exception as e:   # one broken case must not end the run; it is reported as an error
                out = {"passed": False, "error": f"{type(e).__name__}: {str(e)[:300]}"}
            return {"case_id": case["id"], "repeat": rep, "ms": int((time.perf_counter() - t0) * 1000), **out}

    return list(await asyncio.gather(*(one(c, r) for r in range(ctx.repeats) for c in cases)))


def _spend(run_id: str) -> tuple[Optional[float], int]:
    with db.engine().connect() as c:
        cost, n, unknown = c.execute(select(func.coalesce(func.sum(db.llm_calls.c.cost_usd), 0.0), func.count(),
                                            func.sum(func.coalesce(db.llm_calls.c.cost_usd, -1)))
                                     .where(db.llm_calls.c.run_id == run_id)).one()
    if n and unknown is not None and unknown < 0 and not cost:
        return None, n
    return round(cost or 0.0, 6), n


def run_suite(name: str, mode: str = "mock", *, provider: str = "", model: str = "", judge_model: str = "",
              repeats: Optional[int] = None, limit: Optional[int] = None, persist: bool = True) -> dict:
    from . import mockmodel
    from .suites import SUITES
    if mode not in MODES:
        raise SystemExit(f"--mode must be one of {', '.join(MODES)}")
    suite = SUITES[name]
    cfg = config_for(mode, name, provider, model)
    run_id = uuid.uuid4().hex
    if mode == "mock":
        mockmodel.install()
    return _run(suite, name, mode, cfg, run_id, judge_model, repeats, limit, persist)


def _run(suite, name: str, mode: str, cfg: llm.LLMConfig, run_id: str, judge_model: str, repeats: Optional[int],
         limit: Optional[int], persist: bool) -> dict:
    judge = None
    if suite.uses_judge:
        judge = cfg if not judge_model else llm.LLMConfig(cfg.provider, cfg.api_key, judge_model, "eval")
    ctx = Ctx(name, mode, cfg, run_id, judge, repeats or suite.repeats)
    cases = suite.load()[: limit or None]
    t0 = time.time()
    results = asyncio.run(run_cases(ctx, cases, suite.run_case, suite.concurrency))
    metrics = suite.aggregate(results, ctx)
    errors = [r for r in results if r.get("error")]
    metrics["errors"] = len(errors)
    lat = sorted(r["ms"] for r in results) or [0]
    cost, calls = _spend(run_id)
    metrics["llm_calls"] = calls
    if mode == "record":
        (CASSETTES / name).mkdir(parents=True, exist_ok=True)
        (CASSETTES / name / "manifest.json").write_text(json.dumps({"provider": cfg.provider, "model": cfg.model,
                                                                    "recorded_at": int(t0), "git": _git_sha()}, indent=1))
    run = {"id": run_id, "suite": name, "model": cfg.model, "mode": mode, "metrics": metrics,
           "prompt_versions": suite.prompt_versions(), "cost_usd": cost,
           "latency_p50_ms": int(statistics.median(lat)), "latency_p95_ms": lat[min(len(lat) - 1, int(0.95 * len(lat)))],
           "cases": len(results), "failed": sum(1 for r in results if not r.get("passed")), "git_sha": _git_sha(),
           "created_at": t0}
    if persist:
        db.save_eval_run(run, [{"case_id": f"{r['case_id']}#{r['repeat']}" if ctx.repeats > 1 else r["case_id"],
                                "passed": r.get("passed"), "detail": {k: v for k, v in r.items() if k not in ("case_id",)}}
                               for r in results])
    failures = [{"case": r["case_id"], **({"error": r["error"]} if r.get("error") else {}), **(r.get("why") or {})}
                for r in results if not r.get("passed")]
    return {"metrics": metrics, "failures": failures[:40], "run": run, "notes": ctx.notes}


def jsonable(x: Any) -> Any:
    return json.loads(json.dumps(x, default=str))

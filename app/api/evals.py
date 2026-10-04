"""Eval Studio API: eval run history, model leaderboard, human labelling queue, online feedback.

Access: open in local use. When EVAL_ADMINS (comma-separated emails) is set, only those signed-in users may use it.
From the UI only *mock* and *replay* runs can be started (free, no key); record/live runs that spend money are CLI-only.
"""
from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from ..storage import db
from .deps import owner, user

router = APIRouter()
ROOT = Path(__file__).resolve().parents[2]
MATCH = ROOT / "eval" / "datasets" / "match"
LLM_DATA = ROOT / "eval" / "datasets" / "llm"
LABELS = ("strong", "possible", "stretch", "no")


def _admin(request: Request) -> None:
    admins = {e.strip().lower() for e in os.getenv("EVAL_ADMINS", "").split(",") if e.strip()}
    if not admins:
        return
    u = user(request)
    if not u or (u.get("email") or "").lower() not in admins:
        raise HTTPException(403, "Eval Studio is limited to the accounts in EVAL_ADMINS.")


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def _write_jsonl(p: Path, rows: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    tmp.replace(p)


def _suites() -> list[dict]:
    from eval import run as R
    from eval.llm.suites import SUITES as LLM
    det = [{"suite": n, "kind": "deterministic", "description": (fn.__doc__ or "").strip().split("\n")[0]} for n, fn in R.SUITES.items()]
    return det + [{"suite": n, "kind": "llm", "description": s.description} for n, s in LLM.items()]


def _kappa(pairs: list[tuple[str, str]]) -> Optional[float]:
    """Cohen's κ for two labellers on the 4-level label."""
    if len(pairs) < 2:
        return None
    n = len(pairs)
    po = sum(a == b for a, b in pairs) / n
    pe = sum((sum(a == k for a, _ in pairs) / n) * (sum(b == k for _, b in pairs) / n) for k in LABELS)
    return round((po - pe) / (1 - pe), 3) if pe < 1 else 1.0


def label_stats() -> dict:
    pairs, queue = _jsonl(MATCH / "pairs.jsonl"), _jsonl(MATCH / "queue.jsonl")
    double = [p for p in pairs if len(p.get("labels", [])) >= 2]
    return {"pairs_total": len(pairs), "reviewed": sum(1 for p in pairs if p.get("reviewed")),
            "queue": sum(1 for q in queue if not q.get("done")), "double_labelled": len(double),
            "kappa": _kappa([(p["labels"][0]["label"], p["labels"][1]["label"]) for p in double])}


@router.get("/api/eval/overview")
async def overview(request: Request):
    _admin(request)
    from eval import run as R
    from eval.llm.suites import DEFENSE_METRICS, QUALITY_METRIC
    runs = await run_in_threadpool(db.list_eval_runs, "", 1000)
    latest: dict[str, dict] = {}
    for r in runs:                                         # newest first
        latest.setdefault(r["suite"], r)
    base = json.loads(R.BASELINE.read_text()) if R.BASELINE.exists() else {}
    head = []
    for key, (direction, _tol) in {**R.HEADLINE, **R._defense_headline()}.items():
        suite, metric = key.split(".", 1)
        r = latest.get(suite)
        val = (r or {}).get("metrics", {}).get(metric) if r and (r["mode"] in ("deterministic", "mock")) else None
        head.append({"key": key, "label": metric.replace("_", " "), "suite": suite, "direction": direction,
                     "target": 0 if suite in DEFENSE_METRICS and metric in DEFENSE_METRICS[suite] else None,
                     "value": val, "baseline": base.get(key)})
    board: dict[tuple, dict] = {}
    for r in runs:
        if r["mode"] not in ("record", "replay", "live"):
            continue
        k = (r["suite"], r["model"])
        if k in board:
            board[k]["runs"] += 1
            continue
        qm = QUALITY_METRIC.get(r["suite"], "")
        cost100 = round(r["cost_usd"] / r["cases"] * 100, 4) if r.get("cost_usd") is not None and r.get("cases") else None
        board[k] = {"suite": r["suite"], "model": r["model"], "quality_metric": qm, "quality": r["metrics"].get(qm),
                    "cost_per_100": cost100, "p95_ms": r.get("latency_p95_ms"), "runs": 1}
    suites = [{**s, "last_run": latest.get(s["suite"])} for s in _suites()]
    return {"headline": head, "suites": suites, "leaderboard": list(board.values()), "labels": label_stats()}


@router.get("/api/eval/runs")
async def runs(request: Request, suite: str = "", limit: int = 100):
    _admin(request)
    return await run_in_threadpool(db.list_eval_runs, suite, max(1, min(limit, 500)))


@router.get("/api/eval/runs/{run_id}")
async def run_detail(run_id: str, request: Request):
    _admin(request)
    r = await run_in_threadpool(db.load_eval_run, run_id)
    if not r:
        raise HTTPException(404, "Eval run not found.")
    return r


class RunIn(BaseModel):
    suite: str = Field(max_length=60)
    mode: Literal["mock", "replay", "deterministic"] = "mock"


@router.post("/api/eval/run")
async def start_run(body: RunIn, request: Request):
    """Run one suite now (deterministic, mock or replay: free and offline). Returns the stored run."""
    _admin(request)
    from eval import run as R
    from eval.llm.suites import SUITES as LLM
    if body.suite in R.SUITES and body.mode == "deterministic":
        def go():
            t0 = time.time()
            res = R.SUITES[body.suite]()
            rid = os.urandom(16).hex()
            R._persist_deterministic(body.suite, res, t0, rid)
            return rid
        rid = await run_in_threadpool(go)
    elif body.suite in LLM and body.mode in ("mock", "replay"):
        from eval.llm.runner import run_suite
        try:
            res = await run_in_threadpool(run_suite, body.suite, body.mode)
        except SystemExit as e:              # e.g. replay without recorded cassettes
            raise HTTPException(422, str(e))
        rid = res["run"]["id"]
    else:
        raise HTTPException(422, "Unknown suite, or a mode that isn't allowed from the UI (record/live are CLI-only).")
    return await run_in_threadpool(db.load_eval_run, rid)


# ---------- human labelling (match set) ----------
@router.get("/api/eval/labels/queue")
async def label_queue(request: Request, limit: int = 20):
    _admin(request)
    queue = [q for q in _jsonl(MATCH / "queue.jsonl") if not q.get("done")]
    return {"items": queue[: max(1, min(limit, 100))], "stats": label_stats()}


class LabelIn(BaseModel):
    id: str = Field(max_length=200)
    label: Optional[Literal["strong", "possible", "stretch", "no"]] = None
    skip: bool = False
    reviewer: str = Field(default="", max_length=60)
    note: str = Field(default="", max_length=1000)


@router.post("/api/eval/labels")
async def save_label(body: LabelIn, request: Request):
    """A human label moves a queue item into pairs.jsonl (reviewed). A second reviewer's label on the same pair is
    added to `labels` so Cohen's κ can be computed; the first label stays the gold one until adjudicated."""
    _admin(request)
    if not body.skip and not body.label:
        raise HTTPException(422, "Choose a label or skip.")
    reviewer = body.reviewer.strip() or (user(request) or {}).get("email", "") or owner(request)[:12] or "anon"

    def go():
        queue = _jsonl(MATCH / "queue.jsonl")
        item = next((q for q in queue if q["id"] == body.id), None)
        if not item:
            raise HTTPException(404, "Not in the labelling queue.")
        if body.skip:
            item["skipped"] = item.get("skipped", 0) + 1
            queue = [q for q in queue if q["id"] != body.id] + [item]          # to the back
            _write_jsonl(MATCH / "queue.jsonl", queue)
            return label_stats()
        pairs = _jsonl(MATCH / "pairs.jsonl")
        existing = next((p for p in pairs if p["id"] == body.id), None)
        entry = {"reviewer": reviewer, "label": body.label, "note": body.note, "at": int(time.time())}
        if existing:
            if any(x["reviewer"] == reviewer for x in existing.get("labels", [])):
                raise HTTPException(409, "You already labelled this pair.")
            existing.setdefault("labels", []).append(entry)
        else:
            keep = {k: v for k, v in item.items() if k not in ("done", "skipped", "reason")}
            pairs.append({**keep, "label": body.label, "reviewed": True, "reviewer": reviewer, "labels": [entry]})
        item["done"] = True
        _write_jsonl(MATCH / "pairs.jsonl", pairs)
        _write_jsonl(MATCH / "queue.jsonl", queue)
        return label_stats()
    return await run_in_threadpool(go)


# ---------- online feedback ----------
@router.get("/api/feedback/summary")
async def feedback_summary(request: Request):
    _admin(request)
    return await run_in_threadpool(db.feedback_summary, owner(request), not os.getenv("EVAL_ADMINS"))


@router.get("/api/feedback")
async def feedback_list(request: Request, kind: str = "", limit: int = 100):
    _admin(request)
    return await run_in_threadpool(lambda: db.list_feedback(owner(request), kind, max(1, min(limit, 500)), not os.getenv("EVAL_ADMINS")))


@router.post("/api/feedback/{fid}/promote")
async def promote(fid: int, request: Request):
    """Copy a rated/corrected AI output into eval/datasets/llm/feedback_promoted.jsonl for review as a test case."""
    _admin(request)
    rows = await run_in_threadpool(lambda: db.list_feedback(owner(request), "", 5000, True))
    f = next((r for r in rows if r["id"] == fid), None)
    if not f:
        raise HTTPException(404, "Feedback not found.")
    path = LLM_DATA / "feedback_promoted.jsonl"
    existing = _jsonl(path)
    if any(r.get("feedback_id") == fid for r in existing):
        return {"promoted": False, "message": "Already promoted."}
    existing.append({"id": f"fb-{fid}", "feedback_id": fid, "kind": f["kind"], "analysis_id": f["analysis_id"], "job_id": f["job_id"],
                     "item": f["item_id"], "rating": f["rating"], "correction": f["correction"], "comment": f["comment"],
                     "output": f["output"], "model": f["model"], "reviewed": False})
    await run_in_threadpool(_write_jsonl, path, existing)
    await run_in_threadpool(db.mark_feedback_promoted, fid)
    return {"promoted": True, "path": str(path.relative_to(ROOT))}


def sample_for_review(items: list[dict], disagree_ids: set[str], rate: float = 0.2, seed: int = 7) -> list[dict]:
    """Labelling protocol (ROADMAP §7.2): every two-model disagreement plus a random 20 % of agreements."""
    rnd = random.Random(seed)
    out = []
    for it in items:
        if it["id"] in disagree_ids:
            out.append({**it, "reason": "models disagree"})
        elif rnd.random() < rate:
            out.append({**it, "reason": "random audit (20%)"})
    return out

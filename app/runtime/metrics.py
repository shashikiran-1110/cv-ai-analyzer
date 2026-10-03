"""Prometheus metrics (ROADMAP §11) without extra dependencies: counters/histogram sums kept in-process and
rendered in the text exposition format at GET /metrics (protect with METRICS_TOKEN in production)."""
from __future__ import annotations

import threading
from collections import defaultdict

_lock = threading.Lock()
COUNTERS: dict[tuple[str, tuple], float] = defaultdict(float)
HELP = {
    "http_requests_total": "HTTP requests by method, route and status.",
    "http_request_seconds_sum": "Total request time by route.",
    "http_request_seconds_count": "Requests timed by route.",
    "source_fetch_total": "Job-source fetches by source and outcome.",
    "source_jobs_total": "Jobs fetched/kept by source.",
    "agent_runs_total": "Agent runs by kind and outcome.",
    "watch_runs_total": "Saved-search (watch) runs by outcome.",
}


def inc(name: str, value: float = 1.0, **labels) -> None:
    with _lock:
        COUNTERS[(name, tuple(sorted(labels.items())))] += value


def reset() -> None:
    with _lock:
        COUNTERS.clear()


def _esc(v) -> str:
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def render(extra: dict[str, list[tuple[dict, float]]] | None = None) -> str:
    """Text exposition. `extra` = gauges computed at scrape time: {name: [(labels, value), ...]}."""
    lines: list[str] = []
    with _lock:
        items = sorted(COUNTERS.items())
    seen: set[str] = set()
    for (name, labels), v in items:
        if name not in seen:
            seen.add(name)
            lines += [f"# HELP cvm_{name} {HELP.get(name, name)}", f"# TYPE cvm_{name} counter"]
        lab = ",".join(f'{k}="{_esc(x)}"' for k, x in labels)
        lines.append(f"cvm_{name}{{{lab}}} {v:g}" if lab else f"cvm_{name} {v:g}")
    for name, rows in (extra or {}).items():
        lines += [f"# TYPE cvm_{name} gauge"]
        for labels, v in rows:
            lab = ",".join(f'{k}="{_esc(x)}"' for k, x in sorted(labels.items()))
            lines.append(f"cvm_{name}{{{lab}}} {v:g}" if lab else f"cvm_{name} {v:g}")
    return "\n".join(lines) + "\n"

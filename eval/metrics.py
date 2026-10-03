"""Small, dependency-free metric helpers for the eval harness."""
from __future__ import annotations

import math
from typing import Iterable, Sequence


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f, 4)}


def set_counts(pred: Iterable, gold: Iterable) -> tuple[int, int, int]:
    p, g = set(pred), set(gold)
    return len(p & g), len(p - g), len(g - p)


def mae(errors: Sequence[float]) -> float:
    return round(sum(abs(e) for e in errors) / len(errors), 3) if errors else 0.0


def accuracy(flags: Sequence[bool]) -> float:
    return round(sum(flags) / len(flags), 4) if flags else 1.0


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Spearman rank correlation with average ranks for ties (for the match suite)."""
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    if len(xs) < 2:
        return 0.0
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    vy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return round(cov / (vx * vy), 4) if vx and vy else 0.0


def expected_calibration_error(probs: Sequence[float], labels: Sequence[int], bins: int = 10) -> float:
    """ECE for the match suite: probs are scores/100, labels 1 = qualified."""
    if not probs:
        return 0.0
    total, ece = len(probs), 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, p in enumerate(probs) if lo <= p < hi or (b == bins - 1 and p == 1.0)]
        if idx:
            conf = sum(probs[i] for i in idx) / len(idx)
            acc = sum(labels[i] for i in idx) / len(idx)
            ece += len(idx) / total * abs(conf - acc)
    return round(ece, 4)


def token_jaccard(a: str, b: str) -> float:
    import re
    ta, tb = set(re.findall(r"[a-z0-9+#]+", a.lower())), set(re.findall(r"[a-z0-9+#]+", b.lower()))
    return len(ta & tb) / len(ta | tb) if ta | tb else 1.0

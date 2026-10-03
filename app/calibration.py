"""Score calibration (ROADMAP §6.6): score = 100·σ(β0 + Σ βk·componentk), fitted on human-labelled pairs.

Until `app/data/calibration.json` exists (written by `python -m eval.fit_calibration` from ≥ MIN_PAIRS reviewed
pairs), scores use the hand-set linear weights in `matcher.W`. We never ship coefficients fitted on made-up labels.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Optional

PATH = Path(__file__).resolve().parent / "data" / "calibration.json"
FEATURES = ("skills", "requirements", "role", "experience", "semantic")
MIN_PAIRS = 300


@lru_cache(maxsize=1)
def load(path: str = str(PATH)) -> Optional[dict]:
    try:
        cal = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    if cal.get("pairs", 0) < cal.get("min_pairs", MIN_PAIRS) or set(cal.get("coef", {})) != set(FEATURES):
        return None
    return cal


def apply(components: dict[str, float], cal: dict) -> float:
    z = cal["intercept"] + sum(cal["coef"][k] * components[k] for k in FEATURES)
    return 1 / (1 + math.exp(-z))


def fit(rows: list[tuple[dict[str, float], int]], l2: float = 0.01, steps: int = 4000, lr: float = 0.5) -> dict:
    """Plain gradient-descent logistic regression (no numpy needed for a few hundred rows)."""
    w = {k: 0.0 for k in FEATURES}
    b = 0.0
    n = len(rows)
    for _ in range(steps):
        gw = {k: 0.0 for k in FEATURES}
        gb = 0.0
        for x, y in rows:
            p = 1 / (1 + math.exp(-(b + sum(w[k] * x[k] for k in FEATURES))))
            for k in FEATURES:
                gw[k] += (p - y) * x[k]
            gb += p - y
        for k in FEATURES:
            w[k] -= lr * (gw[k] / n + l2 * w[k])
        b -= lr * gb / n
    return {"intercept": round(b, 4), "coef": {k: round(v, 4) for k, v in w.items()}}

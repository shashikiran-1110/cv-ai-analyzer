"""Structured logging (ROADMAP §11). LOG_FORMAT=json emits one JSON object per line with run_id/agent/source when
present; resume text and API keys are never logged (callers don't pass them, and known key shapes are masked)."""
from __future__ import annotations

import json
import logging
import os
import re
import time

_KEYS = re.compile(r"\b(sk-[A-Za-z0-9_-]{6,}|sk-ant-[A-Za-z0-9_-]{6,}|cvx_[A-Za-z0-9_-]{6,})")


class JsonFormatter(logging.Formatter):
    def format(self, r: logging.LogRecord) -> str:
        out = {"ts": round(time.time(), 3), "level": r.levelname.lower(), "logger": r.name,
               "msg": _KEYS.sub("***", r.getMessage())}
        for k in ("run_id", "agent", "source", "route", "status", "ms"):
            if hasattr(r, k):
                out[k] = getattr(r, k)
        if r.exc_info:
            out["exc"] = _KEYS.sub("***", self.formatException(r.exc_info))[-4000:]
        return json.dumps(out, ensure_ascii=False)


def setup() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    root = logging.getLogger()
    if os.getenv("LOG_FORMAT", "text").lower() == "json":
        h = logging.StreamHandler()
        h.setFormatter(JsonFormatter())
        root.handlers[:] = [h]
    elif not root.handlers:
        logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    root.setLevel(level)

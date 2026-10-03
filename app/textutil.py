"""HTML → text and date helpers shared by all job sources."""
from __future__ import annotations

import html as htmllib
import re
from datetime import datetime, timezone
from typing import Any

from bs4 import BeautifulSoup

_BLOCKS = ["p", "div", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "section", "table", "tr"]


def html_to_text(raw: str | None) -> str:
    """Convert posting HTML to plain text, keeping line and bullet structure (requirement parsing needs it)."""
    if not raw:
        return ""
    if "<" not in raw and "&lt;" in raw:  # some APIs (Greenhouse) return entity-escaped HTML
        raw = htmllib.unescape(raw)
    if "<" not in raw:
        return re.sub(r"[ \t]+", " ", raw).strip()
    soup = BeautifulSoup(raw, "html.parser")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for li in soup.find_all("li"):
        li.insert_before("\n• ")
    for blk in soup.find_all(_BLOCKS + ["strong", "b"]):
        if blk.name in ("strong", "b") and blk.parent and blk.parent.name not in ("p", "div", "li"):
            continue
        blk.insert_after("\n")
    text = soup.get_text()
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{2,}", "\n", text).strip()


def parse_date(value: Any) -> str:
    """Best-effort conversion of epoch seconds/ms or ISO-ish strings to an ISO date string ('' if unknown)."""
    if value in (None, "", 0):
        return ""
    try:
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
            v = float(value)
            if v > 1e12:
                v /= 1000
            return datetime.fromtimestamp(v, tz=timezone.utc).isoformat()
        s = str(value).strip().replace("Z", "+00:00")
        for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.fromisoformat(s) if fmt is None else datetime.strptime(s[:19], fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.isoformat()
            except ValueError:
                continue
    except (ValueError, OverflowError, OSError):
        pass
    return ""


def age_hours(iso: str) -> float | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600

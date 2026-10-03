"""PDF resume text extraction and light profile parsing."""
from __future__ import annotations

import io
import re
from datetime import date

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from . import config


class ResumeError(Exception):
    """User-presentable problem with the uploaded resume."""


def extract_text(data: bytes) -> str:
    if len(data) > config.MAX_PDF_BYTES:
        raise ResumeError(f"PDF is too large (max {config.MAX_PDF_BYTES // 1024 // 1024} MB).")
    if not data.startswith(b"%PDF"):
        raise ResumeError("That file doesn't look like a PDF.")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                ok = reader.decrypt("")
            except Exception:
                ok = 0
            if not ok:
                raise ResumeError("This PDF is password-protected. Remove the password and try again.")
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except ResumeError:
        raise
    except (PdfReadError, ValueError, KeyError, OSError) as e:
        raise ResumeError(f"Couldn't read this PDF ({type(e).__name__}). Try re-exporting it.")
    text = re.sub(r"[ \t]+", " ", text).strip()
    if len(text) < 100:
        raise ResumeError(
            "Almost no text could be extracted. If this is a scanned image PDF, "
            "export a text-based PDF (e.g. from Word or Google Docs)."
        )
    return text


_MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_RANGE = re.compile(
    rf"(?:{_MONTHS}\s+)?((?:19|20)\d{{2}})\s*(?:-|–|—|to)\s*(?:(?:{_MONTHS}\s+)?((?:19|20)\d{{2}})|(present|current|now|today))",
    re.IGNORECASE,
)
_EXPLICIT = re.compile(r"(\d{1,2})\+?\s*(?:years?|yrs?)\b", re.IGNORECASE)


def estimate_years(text: str, today: date | None = None) -> float:
    """Years of experience: union of dated ranges, or an explicit 'N years' claim if larger."""
    this_year = (today or date.today()).year
    spans = []
    for m in _RANGE.finditer(text):
        start = int(m.group(1))
        end = this_year if m.group(3) else int(m.group(2))
        if 1970 <= start <= end <= this_year + 1 and end - start <= 40:
            spans.append((start, end))
    spans.sort()
    total, cur_s, cur_e = 0, None, None
    for s, e in spans:
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                total += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        total += cur_e - cur_s
    explicit = 0
    for m in _EXPLICIT.finditer(text):
        window = text[max(0, m.start() - 60): m.end() + 60].lower()
        if "experience" in window and int(m.group(1)) <= 40:
            explicit = max(explicit, int(m.group(1)))
    return float(max(total, explicit))

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


# ---------- identity stripping (ROADMAP §14.2 fairness) ----------
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d")
_URL = re.compile(r"(?:https?://|www\.)\S+|\b(?:linkedin|github)\.com/\S+", re.I)
_PRONOUNS = re.compile(r"^\W*(?:pronouns?\s*:?\s*)?\(?(?:he|she|they|ze|xe)\s*/\s*(?:him|her|them|hir|zir|xem)(?:\s*/\s*\w+)?\)?\W*$", re.I)
_ROLE_WORD = re.compile(r"\b(engineer|developer|analyst|manager|designer|nurse|teacher|scientist|consultant|accountant|"
                        r"specialist|assistant|officer|director|lead|intern|architect|administrator|coordinator|executive|"
                        r"representative|technician|programmer|writer|editor|researcher|recruiter|driver|operator|"
                        r"associate|advisor|adviser|attorney|lawyer|paralegal|pharmacist|therapist|chef|marketer)s?\b", re.I)
_NAME_LINE = re.compile(r"^[^\W\d_][^\W\d_'’.-]*(?:[\s'’.-]+[^\W\d_][^\W\d_'’.-]*){0,4}$")


def strip_identity(text: str) -> str:
    """Remove the candidate's name line, pronouns and contact details before matching.

    Names and pronouns must never influence a score (e.g. a candidate called "Ruby" must not get the Ruby skill,
    and name length must not shift text similarity). Section headings and content are untouched."""
    lines = text.splitlines()
    out, name_done = [], False
    for i, line in enumerate(lines):
        t = line.strip()
        if not t:
            out.append(line)
            continue
        if not name_done:
            name_done = True
            cleaned = _URL.sub(" ", _PHONE.sub(" ", _EMAIL.sub(" ", t))).strip(" |,·-")
            parts = [p.strip() for p in re.split(r"\s+[-–—]\s+|\s*\|\s*", cleaned) if p.strip()]
            if parts and _NAME_LINE.match(parts[0]) and len(parts[0].split()) <= 4 and not _ROLE_WORD.search(parts[0]) \
                    and _sections([parts[0]])[0] == "none":
                rest = " - ".join(parts[1:])                     # keep "Data Engineer" from "Jane Doe - Data Engineer"
                if rest:
                    out.append(rest)
                continue
        if _PRONOUNS.match(t):
            continue
        out.append(_URL.sub(" ", _PHONE.sub(" ", _EMAIL.sub(" ", line))))
    return "\n".join(out)


# ---------- experience (ROADMAP D2/D3): months, Experience section only ----------
_MON = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_MON_RE = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_DATE = (rf"(?:{_MON_RE}\s*'?(\d{{4}}|\d{{2}}(?!\d))"         # Jan 2024 / Jan '24
         r"|(0?[1-9]|1[0-2])\s*[/.-]\s*(\d{4})"                # 06/2023
         r"|(\d{4})\s*[/.-]\s*(0?[1-9]|1[0-2])(?!\d)"          # 2023-06
         r"|((?:19|20)\d{2}))")                                # 2023
_PRESENT = r"(present|current(?:ly)?|now|today|till date|to date|ongoing)"
_RANGE = re.compile(rf"{_DATE}\s*(?:-|–|—|to|until|till)\s*(?:{_DATE}|{_PRESENT})", re.IGNORECASE)
_EXP_HEAD = re.compile(r"^(?:professional |work |relevant |employment |career |industry )?(?:experience|employment(?: history)?|"
                       r"work history|career history|professional background|internships?|work experience)\s*:?$", re.I)
_OTHER_HEAD = re.compile(r"^(?:education(?:al background)?|academic.*|qualifications|(?:personal |academic |key )?projects|"
                         r"certifications?(?: & licenses)?|licenses|publications|awards|honou?rs|volunteer(?:ing| experience)?|"
                         r"(?:technical |core |key )?skills|interests|hobbies|languages|summary|profile|objective|references|"
                         r"achievements|activities|training|courses|coursework)\s*:?$", re.I)
_EDU_LINE = re.compile(r"\b(university|college|school|institute|academy|bachelor|master'?s|ph\.?d|b\.?\s?tech|m\.?\s?tech|"
                       r"b\.?sc|m\.?sc|b\.?e\b|b\.?a\b|mba|degree|gpa|cgpa|graduat|diploma|high school|secondary)\b", re.I)
_EXPLICIT = re.compile(r"(\d{1,2})\+?\s*(?:years?|yrs?)\b", re.IGNORECASE)


def _month(groups: tuple, today: date, is_end: bool) -> tuple[int, bool] | None:
    """(month index, month_precise) from one _DATE match's 7 groups."""
    mon, yy, m1, y1, y2, m2, yonly = groups
    if mon:
        y = int(yy) + (2000 if len(yy) == 2 else 0)
        return y * 12 + _MON[mon.lower()[:3]] - 1, True
    if m1:
        return int(y1) * 12 + int(m1) - 1, True
    if y2:
        return int(y2) * 12 + int(m2) - 1, True
    if yonly:
        y = int(yonly)
        m = 12 if is_end else 1
        if is_end and y == today.year:
            m = today.month
        return y * 12 + m - 1, False
    return None


def _sections(lines: list[str]) -> list[str]:
    """Label each line: 'exp', 'other' or 'none' (before any recognised heading)."""
    out, cur = [], "none"
    for line in lines:
        t = line.strip().strip("•-*:").strip()
        if t and len(t.split()) <= 5 and _EXP_HEAD.match(t):
            cur = "exp"
        elif t and len(t.split()) <= 5 and _OTHER_HEAD.match(t):
            cur = "other"
        out.append(cur)
    return out


def experience(text: str, today: date | None = None) -> dict:
    """Work experience from dated roles: {months, years, precision, spans, explicit_years, method}."""
    today = today or date.today()
    now = today.year * 12 + today.month - 1
    lines = text.splitlines()
    labels = _sections(lines)
    has_exp_heading = "exp" in labels
    spans = []
    for line, label in zip(lines, labels):
        if has_exp_heading and label != "exp":
            continue
        if not has_exp_heading and (label == "other" or _EDU_LINE.search(line)):
            continue
        for m in _RANGE.finditer(line):
            g = m.groups()
            start = _month(g[0:7], today, False)
            end = (now, True) if g[14] else _month(g[7:14], today, True)
            if not start or not end:
                continue
            s_idx, e_idx = start[0], min(end[0], now)
            if s_idx < 1970 * 12 or e_idx < s_idx or e_idx - s_idx > 40 * 12:
                continue
            spans.append({"start": s_idx, "end": e_idx, "precise": start[1] and end[1], "line": line.strip()[:160],
                          "present": bool(g[14])})
    merged: list[list[int]] = []
    for sp in sorted(spans, key=lambda x: x["start"]):
        if merged and sp["start"] <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], sp["end"])
        else:
            merged.append([sp["start"], sp["end"]])
    months = sum(e - s + 1 for s, e in merged)
    explicit = 0
    for m in _EXPLICIT.finditer(text):
        window = text[max(0, m.start() - 60): m.end() + 60].lower()
        if "experience" in window and int(m.group(1)) <= 40:
            explicit = max(explicit, int(m.group(1)))
    fmt = lambda i: f"{i // 12:04d}-{i % 12 + 1:02d}"
    years = max(months / 12, float(explicit))
    return {
        "months": months, "years": round(years, 2), "explicit_years": explicit,
        "precision": "month" if spans and all(s["precise"] for s in spans) else ("year" if spans else "none"),
        "method": "experience section" if has_exp_heading else "all dated lines except education",
        "spans": [{"start": fmt(s["start"]), "end": "present" if s["present"] else fmt(s["end"]),
                   "months": s["end"] - s["start"] + 1, "line": s["line"]} for s in spans],
    }


def estimate_years(text: str, today: date | None = None) -> float:
    """Years of experience: merged dated work spans (month precision), or an explicit 'N years' claim if larger."""
    return experience(text, today)["years"]

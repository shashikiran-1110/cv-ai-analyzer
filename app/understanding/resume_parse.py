"""Resume understanding v2 (ROADMAP §5): text → StructuredProfile, a formatting check, and user corrections.

Rules first (sections, dated roles, bullets with ids, skills with evidence and depth). Corrections are stored
separately and applied on top, so re-parsing never overwrites what the user fixed.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

from .. import matcher, resume
from .. import skills as sk

PARSER_VERSION = 3
_SECTION_WORDS = re.compile(r"\b(experience|employment|education|skills|projects|certifications|summary|profile|"
                            r"languages|awards|publications|volunteering|interests)\b", re.I)
_METRIC = re.compile(r"(\d+(?:[.,]\d+)?\s*(?:%|x|k|m|bn|\+)|[$£€]\s?\d[\d,.]*\s*[kmb]?)", re.I)
_YEAR = re.compile(r"\b(19[6-9]\d|20[0-4]\d)\b")
_INSTITUTION = re.compile(r"\b(university|college|institute|school|academy|polytechnic)\b", re.I)
_SEP = re.compile(r"\s+(?:[|·•–—@]|-|at)\s+|,\s*", re.I)


def _label_sections(lines: list[str]) -> list[str]:
    out, cur = [], "none"
    for line in lines:
        t = line.strip().strip("•-*:").strip()
        if t and len(t.split()) <= 5:
            if resume._EXP_HEAD.match(t):
                cur = "experience"
            elif resume._OTHER_HEAD.match(t):
                w = t.lower()
                cur = ("education" if re.search(r"education|academic|qualification|coursework", w) else
                       "projects" if "project" in w else "skills" if "skill" in w else
                       "certifications" if re.search(r"certif|licen|training|course", w) else
                       "summary" if re.search(r"summary|profile|objective", w) else "other")
        out.append(cur)
    return out


def _fmt(i: int) -> str:
    return f"{i // 12:04d}-{i % 12 + 1:02d}"


def _split_header(text: str) -> tuple[str, str]:
    parts = [p.strip(" ,|-–—") for p in _SEP.split(text) if p and p.strip(" ,|-–—")]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    a, b = parts[0], parts[1]
    if resume._ROLE_WORD.search(b) and not resume._ROLE_WORD.search(a):
        a, b = b, a                                  # "Acme Corp — Data Engineer"
    return a, b


def parse(text: str, today: Optional[date] = None) -> dict:
    today = today or date.today()
    now = today.year * 12 + today.month - 1
    lines = [l.rstrip() for l in text.splitlines()]
    labels = _label_sections(lines)
    has_exp = "experience" in labels
    roles: list[dict] = []
    projects: list[dict] = []
    education: list[dict] = []
    skills_list: set[str] = set()
    bullet_n = 0
    current: Optional[dict] = None
    pending_header = ""
    for line, label in zip(lines, labels):
        t = line.strip()
        if not t or (len(t.split()) <= 5 and (resume._EXP_HEAD.match(t.strip(":")) or resume._OTHER_HEAD.match(t.strip(":")))):
            continue
        is_bullet = bool(matcher._BULLET.match(t))
        body = matcher._BULLET.sub("", t).strip()
        in_work = label == "experience" or (not has_exp and label == "none" and not resume._EDU_LINE.search(t))
        if label == "education" or (label != "experience" and resume._EDU_LINE.search(t) and matcher.education_level(t)):
            years = [int(y) for y in _YEAR.findall(t)]
            education.append({"text": body[:200], "degree_level": matcher.education_level(body),
                              "institution": next((p for p in re.split(r",|\||–|—| - ", body) if _INSTITUTION.search(p)), "").strip(),
                              "field": (re.search(r"\bin\s+([A-Z][\w &/-]{2,60})", body) or [None, ""])[1].strip(),
                              "start": str(min(years)) if len(years) > 1 else "", "end": str(max(years)) if years else ""})
            continue
        if label == "skills":
            skills_list |= sk.extract_skills(body)
            continue
        if label == "projects":
            if is_bullet and projects:
                bullet_n += 1
                projects[-1]["bullets"].append({"id": f"b{bullet_n}", "text": body, "skills": sorted(sk.extract_skills(body))})
            else:
                projects.append({"id": f"p{len(projects) + 1}", "name": body[:120], "bullets": [], "skills": sorted(sk.extract_skills(body))})
            continue
        if not in_work:
            continue
        m = resume._RANGE.search(t)
        if m:
            g = m.groups()
            start = resume._month(g[0:7], today, False)
            end = (now, True) if g[14] else resume._month(g[7:14], today, True)
            header = (t[:m.start()] + " " + t[m.end():]).strip(" ,|-–—()")
            if not header and pending_header:
                header = pending_header
                if current and current["bullets"] and current["bullets"][-1]["text"] == pending_header:
                    current["bullets"].pop()
            title, company = _split_header(header)
            if start and end and start[0] <= min(end[0], now):
                current = {"id": f"r{len(roles) + 1}", "title": title[:120], "company": company[:120],
                           "start": _fmt(start[0]), "end": "present" if g[14] else _fmt(min(end[0], now)),
                           "months": min(end[0], now) - start[0] + 1, "date_precision": "month" if start[1] and end[1] else "year",
                           "bullets": [], "source": "rules", "line": t[:200]}
                roles.append(current)
                pending_header = ""
                continue
        if current is not None and (is_bullet or len(body.split()) > 6):
            bullet_n += 1
            current["bullets"].append({"id": f"b{bullet_n}", "text": body, "skills": sorted(sk.extract_skills(body)),
                                       "metrics": _METRIC.findall(body)[:5]})
        else:
            pending_header = body
    # skills with evidence & depth
    evidence: dict[str, dict] = {}
    for r in roles:
        for item in [{"id": r["id"], "skills": sorted(sk.extract_skills(r["title"]))}] + r["bullets"]:
            for s in item["skills"]:
                e = evidence.setdefault(s, {"name": s, "evidence": [], "roles": set(), "source": "experience"})
                e["evidence"].append(item["id"])
                e["roles"].add(r["id"])
    for p in projects:
        for item in [p] + p["bullets"]:
            for s in item["skills"]:
                e = evidence.setdefault(s, {"name": s, "evidence": [], "roles": set(), "source": "projects"})
                e["evidence"].append(item["id"])
    for s in skills_list:
        evidence.setdefault(s, {"name": s, "evidence": [], "roles": set(), "source": "skills_list"})
    for s in sk.extract_skills(text):             # mentioned elsewhere (summary etc.)
        evidence.setdefault(s, {"name": s, "evidence": [], "roles": set(), "source": "mentioned"})
    by_id = {r["id"]: r for r in roles}
    skills_out = []
    for s, e in sorted(evidence.items()):
        months = sum(by_id[r]["months"] for r in e["roles"])
        last = max((by_id[r]["end"] for r in e["roles"]), default="")
        n_exp = sum(1 for x in e["evidence"] if x.startswith(("b", "r")) and e["source"] == "experience")
        strength = "strong" if n_exp >= 2 else "moderate" if (n_exp == 1 or e["source"] == "projects") else "weak"
        skills_out.append({"name": s, "evidence": e["evidence"], "months_used": months, "last_used": last,
                           "source": e["source"], "strength": strength, "category": sk.category_of(s)})
    exp = resume.experience(text, today)
    warnings = []
    if not has_exp:
        warnings.append("No 'Experience' heading found; work dates were read from all dated lines.")
    if not roles:
        warnings.append("No dated roles found. Add month and year ranges (e.g. 'Jan 2021 – Present') to each job.")
    if any(len(_SECTION_WORDS.findall(l)) >= 2 and len(l.split()) <= 8 for l in lines):
        warnings.append("Two-column or table layout suspected (section headings share a line); some text may be out of order.")
    if any(r["date_precision"] == "year" for r in roles):
        warnings.append("Some roles only have years, so experience is approximate.")
    return {"parser_version": PARSER_VERSION, "headline": next((l.strip() for l in resume.strip_identity(text).splitlines() if l.strip()), "")[:160],
            "roles": roles, "education": education, "projects": projects, "skills": skills_out,
            "education_level": matcher.education_level(text),
            "experience_months": {"total": exp["months"], "explicit_years": exp["explicit_years"]},
            "parse": {"warnings": warnings, "confidence": round(max(0.2, 1 - 0.2 * len(warnings)), 2)}}


def formatting_check(text: str, profile: dict) -> list[dict]:
    """ATS-style readability checklist (ROADMAP §9.4)."""
    words = len(text.split())
    bullets = [b for r in profile["roles"] for b in r["bullets"]]
    quantified = sum(1 for b in bullets if b.get("metrics"))
    heads = {h for h in ("experience", "education", "skills") if re.search(rf"^\W*{h}", text, re.I | re.M)}
    two_col = any("Two-column" in w for w in profile["parse"]["warnings"])
    checks = [
        ("Text can be extracted", len(text) >= 400, "Readable text found." if len(text) >= 400 else
         "Very little text; if this is a scanned PDF, export a text-based PDF."),
        ("Standard section headings", len(heads) == 3, "Found: " + (", ".join(sorted(heads)) or "none") +
         ". Use the headings Experience, Education and Skills so screening software files your details correctly."),
        ("Contact details present", bool(resume._EMAIL.search(text) or resume._PHONE.search(text)),
         "Email or phone found." if (resume._EMAIL.search(text) or resume._PHONE.search(text)) else
         "No email/phone found in the text layer; if it's in a header image or text box, applicant systems may miss it."),
        ("Single-column layout", not two_col, "Looks single-column." if not two_col else
         "Two-column/table layout suspected: applicant tracking systems often scramble it. Prefer one column."),
        ("Dated roles (month and year)", bool(profile["roles"]) and all(r["date_precision"] == "month" for r in profile["roles"]),
         f"{len(profile['roles'])} dated role(s) found."),
        ("Achievements quantified", bool(bullets) and quantified / max(1, len(bullets)) >= 0.3,
         f"{quantified} of {len(bullets)} experience bullets include a number (aim for at least a third)."),
        ("Length", 300 <= words <= 1200, f"{words} words (300–1200 is typical for 1–2 pages)."),
    ]
    return [{"label": l, "ok": bool(ok), "detail": d} for l, ok, d in checks]


def apply_corrections(profile: dict, corr: dict) -> dict:
    """User corrections beat parser output (ROADMAP §5.3). Returns a new profile dict."""
    p = {**profile, "roles": [dict(r) for r in profile["roles"]], "skills": [dict(s) for s in profile["skills"]]}
    for r in p["roles"]:
        c = (corr.get("roles") or {}).get(r["id"]) or {}
        for k in ("title", "company", "start", "end"):
            if c.get(k):
                r[k] = c[k]
        r["ignore"] = bool(c.get("ignore"))
        r["months"] = _months(r["start"], r["end"]) or r["months"]
    remove = {s.lower() for s in corr.get("skills_remove") or []}
    p["skills"] = [s for s in p["skills"] if s["name"].lower() not in remove]
    have = {s["name"] for s in p["skills"]}
    for name in corr.get("skills_add") or []:
        canon = sk.canonical(name) or name
        if canon not in have:
            p["skills"].append({"name": canon, "evidence": [], "months_used": 0, "last_used": "", "source": "user",
                                "strength": "user", "category": sk.category_of(canon)})
    if corr.get("degree") is not None:
        p["education_level"] = corr["degree"] or None
    p["experience_months"] = {**p["experience_months"], "total": corrected_months(p, corr)}
    p["corrected"] = bool(corr)
    return p


def _months(start: str, end: str) -> int:
    try:
        s = int(start[:4]) * 12 + int(start[5:7]) - 1
        if end == "present":
            t = date.today()
            e = t.year * 12 + t.month - 1
        else:
            e = int(end[:4]) * 12 + int(end[5:7]) - 1
        return max(0, e - s + 1)
    except (ValueError, IndexError, TypeError):
        return 0


def corrected_months(p: dict, corr: dict) -> int:
    if corr.get("years_override") is not None:
        return int(round(float(corr["years_override"]) * 12))
    spans = []
    for r in p["roles"]:
        if r.get("ignore"):
            continue
        m = _months(r["start"], r["end"])
        if m:
            s = int(r["start"][:4]) * 12 + int(r["start"][5:7]) - 1
            spans.append((s, s + m - 1))
    spans.sort()
    total, cur = 0, None
    for s, e in spans:
        if cur and s <= cur[1] + 1:
            cur[1] = max(cur[1], e)
        else:
            if cur:
                total += cur[1] - cur[0] + 1
            cur = [s, e]
    if cur:
        total += cur[1] - cur[0] + 1
    return total if spans else p["experience_months"]["total"]


def matching_inputs(text: str, corr: dict) -> dict:
    """What the matcher needs from a (possibly corrected) resume: years, skills to add/remove, degree."""
    if not corr:
        return {"years": None, "add": set(), "remove": set(), "degree": None}
    p = apply_corrections(parse(text), corr)
    years = p["experience_months"]["total"] / 12 if (corr.get("roles") or corr.get("years_override") is not None) else None
    return {"years": years, "add": {sk.canonical(s) or s for s in corr.get("skills_add") or []},
            "remove": {sk.canonical(s) or s for s in corr.get("skills_remove") or []},
            "degree": corr.get("degree") if corr.get("degree") is not None else None}

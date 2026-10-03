"""Deterministic resume-vs-job scoring.

score = 60% skill coverage + 25% role/title fit + 15% experience fit  (0-100)
Skills in a "preferred / nice to have" section count half; soft skills count half.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from . import skills as sk

W_SKILLS, W_TITLE, W_EXP = 0.60, 0.25, 0.15

_PREFERRED_HEADING = re.compile(
    r"(?im)^\W*(nice[\s-]*to[\s-]*haves?|preferred|bonus|good to have|desirable|"
    r"a plus|pluses|extra credit|what would (?:make you|set you)|ideal(?:ly)?)\b.*$"
)
_REQ_YEARS = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*\d{1,2}\s*\+?\s*)?(?:years?|yrs?)\b[^.\n]{0,40}?experience"
    r"|experience[^.\n]{0,40}?(\d{1,2})\s*\+?\s*(?:years?|yrs?)",
    re.IGNORECASE,
)
_SENIORITY_YEARS = [
    (re.compile(r"\b(principal|staff|head of|director)\b", re.I), 8),
    (re.compile(r"\b(lead|manager)\b", re.I), 6),
    (re.compile(r"\b(senior|sr\.?)\b", re.I), 5),
    (re.compile(r"\b(junior|jr\.?|entry|graduate|intern|trainee|associate)\b", re.I), 0),
]
_TITLE_NOISE = {
    "senior", "sr", "junior", "jr", "lead", "principal", "staff", "associate", "intern", "ii", "iii", "i",
    "the", "and", "of", "for", "a", "an", "in", "at", "remote", "hybrid", "contract", "full", "time", "part",
    "engineer", "developer", "specialist", "analyst", "manager",  # kept below as weak tokens
}
_WEAK_TITLE = {"engineer", "developer", "specialist", "analyst", "manager"}
_STOP = set(
    "a an and are as at be by for from has have in is it its of on or our that the their this to we will with you your "
    "about all also any can more must other per such team work working years year experience strong ability "
    "skills including etc new over us who what when which role job responsibilities requirements qualifications "
    "company looking join help build using use well within across candidate position opportunity benefits".split()
)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z][a-z+#.\-]{2,}", text.lower())


def split_requirements(description: str) -> tuple[str, str]:
    """Split a posting into (required text, preferred text) at a 'Nice to have' style heading."""
    m = _PREFERRED_HEADING.search(description)
    if m and m.start() > 0.15 * len(description):
        return description[: m.start()], description[m.start():]
    return description, ""


def required_years(title: str, description: str) -> tuple[float | None, bool]:
    """(years, inferred). Prefers an explicit 'N years of experience' statement."""
    found = []
    for m in _REQ_YEARS.finditer(description):
        n = int(m.group(1) or m.group(2))
        if 0 < n <= 20:
            found.append(n)
    if found:
        return float(min(found)), False
    for pat, yrs in _SENIORITY_YEARS:
        if pat.search(title):
            return float(yrs), True
    return None, True


def title_fit(job_title: str, resume_text: str, resume_head: str) -> float:
    """0-1: how well the posting's role words appear in the resume (headline weighted)."""
    toks = [t for t in re.findall(r"[a-z+#.]+", job_title.lower()) if t not in _TITLE_NOISE or t in _WEAK_TITLE]
    if not toks:
        return 0.5
    low, head = resume_text.lower(), resume_head.lower()
    weights = {t: (0.4 if t in _WEAK_TITLE else 1.0) for t in toks}
    total = sum(weights.values())
    hit = sum(w for t, w in weights.items() if re.search(rf"\b{re.escape(t)}", low))
    frac = hit / total
    phrase = " ".join(toks)
    bonus = 0.0
    if phrase in low:
        bonus = 0.3
    if any(re.search(rf"\b{re.escape(t)}", head) for t in toks if t not in _WEAK_TITLE):
        bonus += 0.1
    return min(1.0, frac * 0.7 + bonus)


def _fallback_keywords(description: str, n: int = 12) -> set[str]:
    """For postings with few recognised skills (non-tech roles): most repeated meaningful words."""
    counts = Counter(t for t in _tokens(description) if t not in _STOP and len(t) > 3)
    return {w for w, c in counts.most_common(n) if c >= 2}


@dataclass
class ResumeProfile:
    text: str
    skills: set[str]
    years: float
    head: str

    @classmethod
    def build(cls, text: str, years: float) -> "ResumeProfile":
        return cls(text=text, skills=sk.extract_skills(text), years=years, head=text[:400])


def score_job(job: dict, profile: ResumeProfile) -> dict:
    desc = job.get("description") or ""
    title = job.get("title") or ""
    req_text, pref_text = split_requirements(desc)
    # title text counts as a requirement signal too
    req_skills = sk.extract_skills(req_text + "\n" + title)
    pref_skills = sk.extract_skills(pref_text) - req_skills

    weights: dict[str, float] = {}
    for s in req_skills:
        weights[s] = 0.5 if sk.category_of(s) == sk.SOFT_CATEGORY else 1.0
    for s in pref_skills:
        weights[s] = 0.5 * (0.5 if sk.category_of(s) == sk.SOFT_CATEGORY else 1.0)

    keyword_mode = len(req_skills) < 3 and len(desc) >= 200
    resume_tokens = set(_tokens(profile.text))
    if keyword_mode:
        kws = _fallback_keywords(desc)
        matched_kw = sorted(k for k in kws if k in resume_tokens)
        missing_kw = sorted(k for k in kws if k not in resume_tokens)
    else:
        matched_kw = missing_kw = []

    matched = sorted(s for s in weights if s in profile.skills)
    missing = sorted(s for s in weights if s not in profile.skills)
    if weights:
        skill_score = sum(weights[s] for s in matched) / sum(weights.values())
        if keyword_mode and (matched_kw or missing_kw):
            kw_score = len(matched_kw) / (len(matched_kw) + len(missing_kw))
            skill_score = (skill_score * len(weights) + kw_score * 3) / (len(weights) + 3)
    elif keyword_mode and (matched_kw or missing_kw):
        skill_score = len(matched_kw) / (len(matched_kw) + len(missing_kw))
    else:
        skill_score = 0.0

    t_score = title_fit(title, profile.text, profile.head)
    req_yrs, inferred = required_years(title, desc)
    if req_yrs is None:
        e_score = 0.85
    elif req_yrs == 0:
        e_score = 1.0
    elif profile.years <= 0:
        e_score = 0.4
    else:
        e_score = min(1.0, profile.years / req_yrs)

    total = W_SKILLS * skill_score + W_TITLE * t_score + W_EXP * e_score
    required_missing = sorted(s for s in req_skills if s not in profile.skills)
    low_conf = len(desc) < 80 or (not weights and not keyword_mode)
    if len(desc) < 80:  # title-only: can't judge skills fairly
        total = min(total, 0.45)

    return {
        "id": job["id"], "title": title, "company": job.get("company", ""),
        "location": job.get("location", ""), "url": job.get("url", ""), "posted": job.get("posted", ""),
        "score": round(total * 100),
        "components": {
            "skills": round(skill_score * 100), "role": round(t_score * 100), "experience": round(e_score * 100),
        },
        "matched_skills": matched, "missing_skills": missing, "required_missing": required_missing,
        "matched_keywords": matched_kw, "missing_keywords": missing_kw,
        "required_years": req_yrs, "required_years_inferred": inferred,
        "confidence": "low" if low_conf else "high",
    }


def aggregate(results: list[dict], profile: ResumeProfile, threshold: int) -> dict:
    n = len(results)
    scores = [r["score"] for r in results]
    demand: Counter = Counter()
    gap: Counter = Counter()
    for r in results:
        demand.update(r["matched_skills"])
        demand.update(r["missing_skills"])
        gap.update(r["missing_skills"])
    owned = Counter({s: demand[s] - gap[s] for s in demand if s in profile.skills})
    in_demand_total = {s: demand[s] for s in demand}
    buckets = [0] * 5  # 0-19, 20-39, 40-59, 60-79, 80-100
    for s in scores:
        buckets[min(4, s // 20)] += 1
    return {
        "job_count": n,
        "avg_score": round(sum(scores) / n) if n else 0,
        "qualifying": sum(1 for s in scores if s >= threshold),
        "threshold": threshold,
        "distribution": buckets,
        "resume_skills": sorted(profile.skills),
        "resume_years": profile.years,
        "skill_gaps": [
            {"skill": s, "category": sk.category_of(s), "jobs": c, "pct": round(100 * c / n) if n else 0}
            for s, c in gap.most_common(15)
        ],
        "skill_strengths": [
            {"skill": s, "category": sk.category_of(s), "jobs": c, "pct": round(100 * c / n) if n else 0}
            for s, c in owned.most_common(12) if c > 0
        ],
        "unused_skills": sorted(s for s in profile.skills if s not in in_demand_total),
    }

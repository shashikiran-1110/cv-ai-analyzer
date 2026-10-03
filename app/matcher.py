"""Deterministic, explainable resume-vs-job scoring (matcher v2).

score (0-100) = 40% skills + 20% requirements + 15% role fit + 15% experience + 10% semantic similarity
                minus small penalties for hard blockers (e.g. a required degree level not found).

- skills:        taxonomy skills; required 1.0, preferred ("nice to have") 0.5, soft skills half weight
- requirements:  each requirement *line* of the posting is checked against the resume (skills owned,
                 years, degree, or key terms) and marked met / partial / missing
- role fit:      the posting's role words in the resume (headline weighted)
- experience:    required years (stated, or inferred from seniority) vs years found on the resume
- semantic:      TF-IDF cosine similarity between resume and posting (catches overlap outside the taxonomy)
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from . import skills as sk

W = {"skills": 0.40, "requirements": 0.20, "role": 0.15, "experience": 0.15, "semantic": 0.10}

_PREFERRED_HEADING = re.compile(
    r"(?im)^\W*(nice[\s-]*to[\s-]*haves?|preferred|bonus|good to have|desirable|"
    r"a plus|pluses|extra credit|what would (?:make you|set you)|ideal(?:ly)?)\b.*$"
)
_REQ_YEARS = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*\d{1,2}\s*\+?\s*)?(?:years?|yrs?)\b[^.\n]{0,40}?experience"
    r"|experience[^.\n]{0,40}?(\d{1,2})\s*\+?\s*(?:years?|yrs?)",
    re.IGNORECASE,
)
_LINE_YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*\d{1,2}\s*\+?\s*)?(?:years?|yrs?)\b", re.I)
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
    "company looking join help build using use well within across candidate position opportunity benefits "
    "able excellent good great solid proven knowledge understanding familiarity familiar proficiency proficient "
    "plus bonus nice preferred required requirement must should would like ideal ideally least minimum demonstrated "
    "relevant related similar equivalent field environment environments based high level highly hands ensure "
    "within into through both each other them they these those where while you'll we're you're it's".split()
)

# ---------- education ----------
_NOT_DEGREE = re.compile(r"\b(scrum|data|branch|quarter|web|ring|post|head|station|chess|grand)[\s-]?master|"
                         r"master\s+(?:data|branch|class|plan|key|list|record|copy|bedroom|craftsman|of ceremon)|"
                         r"\bmaster(?:ed|y|ing)\b|\bmasterclass\b", re.I)
_EDU = [
    ("PhD", 4, re.compile(r"\b(ph\.?\s?d|doctorate|doctoral degree|d\.?phil)\b", re.I)),
    # ROADMAP D6: "master" only counts with degree context ("Certified Scrum Master" is not a degree)
    ("Master's", 3, re.compile(r"\bmaster'?s\b(?!\s+(?:data|branch|class))|\bmasters?\s+(?:degree|of|in)\b|"
                               r"\bmaster\s+of\s+(?:science|arts|business|engineering|technology|computer|education|"
                               r"public|fine|laws?|philosophy|commerce|information)|\bm\.\s?sc\b|\bmsc\b|\bm\.s\.(?=\s|$)|"
                               r"\bm\.?s\.?\s+in\b|\bmba\b|\bm\.?eng\b|\bm\.?\s?tech\b|post-?graduate degree", re.I)),
    ("Bachelor's", 2, re.compile(r"\b(bachelor'?s?|b\.\s?sc|bsc|b\.s\.|b\.a\.|b\.?eng|b\.?\s?tech|undergraduate degree|"
                                 r"(?:university|college) degree|degree in)\b", re.I)),
]
_EDU_RANK = {name: rank for name, rank, _ in _EDU}
_DEGREE_CUE = re.compile(r"\b(degree|bachelor'?s?|ph\.?\s?d|doctorate|bsc|msc|b\.s\.|m\.s\.|mba|b\.?\s?tech|m\.?\s?tech)\b|"
                         r"\bmaster'?s\b|\bmasters?\s+(?:degree|of|in)\b", re.I)
_SOFTENER = re.compile(r"\b(or equivalent|equivalent (?:practical |work )?experience|preferred|a plus|nice to have|"
                       r"desirable|or similar experience|bonus)\b", re.I)


def _degree_text(text: str) -> str:
    return _NOT_DEGREE.sub(" ", text)


def education_level(text: str) -> Optional[str]:
    """Highest degree level mentioned (resume side)."""
    text = _degree_text(text)
    for name, _, pat in _EDU:
        if pat.search(text):
            return name
    return None


def required_education(lines: list[tuple[str, bool]]) -> tuple[Optional[str], bool, str]:
    """(level, strict, line) from requirement lines. Lowest level named in a degree line is the bar."""
    for text, preferred in lines:
        text = _degree_text(text)
        if not _DEGREE_CUE.search(text):
            continue
        levels = [name for name, _, pat in _EDU if pat.search(text)]
        level = min(levels, key=lambda n: _EDU_RANK[n]) if levels else "Bachelor's"
        strict = not preferred and not _SOFTENER.search(text)
        return level, strict, text
    return None, False, ""


# ---------- text utils ----------
def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z][a-z+#.\-]{2,}", text.lower())


def _stem(w: str) -> str:
    w = w.strip(".-")
    for suf in ("ing", "ies", "es", "s", "ed"):
        if len(w) > 5 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def _content_terms(text: str) -> list[str]:
    return [_stem(t) for t in _tokens(text) if t not in _STOP and len(t) > 3]


def split_requirements(description: str) -> tuple[str, str]:
    """Split a posting into (required text, preferred text) at a 'Nice to have' style heading."""
    m = _PREFERRED_HEADING.search(description)
    if m and m.start() > 0.15 * len(description):
        return description[: m.start()], description[m.start():]
    return description, ""


# ---------- requirement lines ----------
_H_REQ = re.compile(r"(requirement|qualification|what you(?:'ll)? (?:need|bring)|who you are|about you|you have|"
                    r"you(?:'ll)? have|must[\s-]have|skills|what we(?:'re| are) looking for|experience|your profile|"
                    r"you should|you bring|ideal candidate)", re.I)
_H_PREF = re.compile(r"(nice[\s-]*to[\s-]*have|preferred|bonus|good to have|desirable|a plus|pluses|extra credit|ideal)", re.I)
_H_SKIP = re.compile(r"(benefit|perk|what we offer|we offer|about us|about the company|who we are|why (?:join|us|work)|"
                     r"compensation|salary|equal opportunit|diversity|our values|how to apply|interview process|"
                     r"responsibilit|what you(?:'ll)? do|the role|about the role|day[\s-]to[\s-]day|your mission|"
                     r"in this role|you will|what you will)", re.I)
_CUE = re.compile(r"\b(experience|proficien|knowledge|familiar|degree|must|required|ability to|skills?|years?|"
                  r"understanding|expertise|background in|certif|fluent|hands-on)\b", re.I)
_BULLET = re.compile(r"^\s*(?:[•\-*·▪►◦–]|\d{1,2}[.)])\s*")


_SENT_SPLIT = re.compile(r"(?<=[.!?;])\s+(?=[A-Z0-9•(])")


def requirement_lines(description: str) -> list[tuple[str, bool]]:
    """Extract (line, is_preferred) requirement statements, section-aware.

    v2 (eval-driven): short bullets that name a skill or a meaningful term are kept (F1); a prose paragraph after
    the bullets of a Requirements section ends that section (F2); postings without headings/bullets are split into
    sentences and the requirement-like sentences kept (F3)."""
    lines = [l.strip() for l in description.splitlines() if l.strip()]
    section: Optional[str] = None
    found_req = False
    bullets_in_section = 0
    out: list[tuple[str, bool]] = []
    loose: list[tuple[str, bool]] = []
    for raw in lines:
        is_bullet = bool(_BULLET.match(raw))
        text = _BULLET.sub("", raw).strip()
        is_heading = not is_bullet and len(text) <= 70 and (text.endswith(":") or len(text.split()) <= 7)
        if is_heading:
            new = ("pref" if _H_PREF.search(text) else "skip" if _H_SKIP.search(text) else
                   "req" if _H_REQ.search(text) else None)
            if new:
                section, bullets_in_section = new, 0
                found_req = found_req or new == "req"
                continue
        if section in ("req", "pref"):
            if (not is_bullet and bullets_in_section and (len(text) > 100 or ". " in text)
                    and not _CUE.search(text) and not sk.extract_skills(text)):
                section = None                       # F2: prose after the bullets is not a requirement
                continue
            if not (2 <= len(text) <= 320) or (len(text) < 15 and not (sk.extract_skills(text) or _content_terms(text))):
                continue                             # F1: "Python", "SQL", "AWS and Docker" are real requirements
            bullets_in_section += is_bullet
            out.append((text, section == "pref"))
        elif section != "skip":
            for part in (_SENT_SPLIT.split(text) if len(text) > 160 else [text]):     # F3
                part = part.strip()
                if 15 <= len(part) <= 320 and (is_bullet or _CUE.search(part)) and _CUE.search(part):
                    loose.append((part.rstrip("."), bool(_H_PREF.search(part))))
    if not found_req and not any(p for _, p in out):
        out = loose + out
    return out[:25]


# ---------- semantic similarity ----------
def _grams(text: str) -> Counter:
    terms = _content_terms(text)
    c = Counter(terms)
    c.update(f"{a} {b}" for a, b in zip(terms, terms[1:]))
    return c


def corpus_idf(docs: list[str]) -> dict[str, float]:
    df: Counter = Counter()
    for d in docs:
        df.update(set(_grams(d)))
    n = len(docs)
    return {t: math.log((1 + n) / (1 + c)) + 1 for t, c in df.items()}


def semantic_similarity(a: str, b: str, idf: Optional[dict[str, float]] = None) -> float:
    ga, gb = _grams(a), _grams(b)
    if not ga or not gb:
        return 0.0
    w = (lambda t: idf.get(t, 1.0)) if idf else (lambda t: 1.0)
    va = {t: (1 + math.log(c)) * w(t) for t, c in ga.items()}
    vb = {t: (1 + math.log(c)) * w(t) for t, c in gb.items()}
    dot = sum(v * vb.get(t, 0.0) for t, v in va.items())
    na = math.sqrt(sum(v * v for v in va.values()))
    nb = math.sqrt(sum(v * v for v in vb.values()))
    return dot / (na * nb) if na and nb else 0.0


# ---------- years / role ----------
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
    education: Optional[str] = None
    terms: frozenset = frozenset()
    implied: dict = field(default_factory=dict)       # skill → owned skill that implies it (ontology)
    lines: tuple = ()                                  # (resume line, skills on it) for evidence pointers
    eligibility: dict = field(default_factory=dict)   # work authorisation, languages, licences… (profile)

    @classmethod
    def build(cls, text: str, years: float, extra_skills: set[str] | None = None,
              corrections: dict | None = None) -> "ResumeProfile":
        """`corrections` are the user's profile fixes (ROADMAP §5.3); they beat what the parser read."""
        from .resume import strip_identity           # names/contacts never reach matching (ROADMAP §14.2)
        raw, text = text, strip_identity(text)
        skills, education = sk.extract_skills(text), education_level(text)
        if corrections:
            from .understanding.resume_parse import matching_inputs
            mi = matching_inputs(raw, corrections)
            years = mi["years"] if mi["years"] is not None else years
            skills = (skills | mi["add"]) - mi["remove"]
            if mi["degree"] is not None:
                education = mi["degree"] or None
        from .ontology import implied_by
        skills = skills | (extra_skills or set())
        lines = tuple((ln.strip(" -•*\t"), frozenset(sk.extract_skills(ln))) for ln in text.splitlines()
                      if len(ln.split()) >= 2)
        return cls(text=text, skills=skills, years=years, head=text[:400], education=education,
                   terms=frozenset(_content_terms(text)), implied=implied_by(skills), lines=lines,
                   eligibility=dict((corrections or {}).get("eligibility") or {}))


def _evidence_for(profile: ResumeProfile, skills: list[str] = (), terms: set[str] = frozenset()) -> str:
    """The resume line that best supports a requirement (for the requirement matrix)."""
    if skills:
        want = set(skills)
        best = max(profile.lines, key=lambda x: len(want & x[1]), default=None)
        if best and want & best[1]:
            return best[0][:220]
    if terms:
        scored = [(len(terms & set(_content_terms(ln))), ln) for ln, _ in profile.lines]
        n, ln = max(scored, default=(0, ""))
        if n:
            return ln[:220]
    return ""


def _line_assess(text: str, profile: ResumeProfile) -> Optional[dict]:
    """One requirement line → {coverage, missing, how, via, evidence}; None if it can't be judged."""
    line_skills, _neg = sk.extract_posting_skills(text)
    if not line_skills and _neg:
        return None                          # "No Java required": nothing to check on this line
    if line_skills:
        from .ontology import credit
        credits = {s: credit(s, profile.skills, profile.implied) for s in sorted(line_skills)}
        owned = [s for s, c in credits.items() if c[0] >= 1.0]
        missing = sorted(s for s, c in credits.items() if c[0] < 1.0)
        via = [f"{s} (implied by {c[2]})" if c[1] == "implied" else f"{s} ~ you have {c[2]} (related)"
               for s, c in credits.items() if c[1] in ("implied", "related")]
        how = "related skill" if any(c[1] == "related" for c in credits.values()) else \
              "implied skill" if any(c[1] == "implied" for c in credits.values()) else "exact skill"
        ev = _evidence_for(profile, [s if credits[s][1] == "exact" else credits[s][2] for s in credits if credits[s][0] > 0])
        if owned and re.search(r"\bor\b|/|\beither\b|\bsimilar\b|\bequivalent\b", text, re.I):
            return {"coverage": 1.0, "missing": [], "how": how, "via": via, "evidence": ev}   # "Tableau or Power BI"
        best_alt = max((c[0] for c in credits.values()), default=0.0)
        cov = sum(c[0] for c in credits.values()) / len(credits)
        if re.search(r"\bor\b|/|\beither\b|\bsimilar\b|\bequivalent\b", text, re.I):
            cov = max(cov, best_alt)         # alternatives: the best one counts
        return {"coverage": cov, "missing": missing, "how": how if cov > 0 else "not found", "via": via, "evidence": ev}
    m = _LINE_YEARS.search(text)
    if m and re.search(r"experience|exp\b", text, re.I):
        need = int(m.group(1))
        cov = 1.0 if need == 0 else (min(1.0, profile.years / need) if profile.years else 0.3)
        return {"coverage": cov, "missing": [], "how": "years check", "via": [],
                "evidence": f"About {profile.years:.1f} years of dated experience on your resume." if profile.years else ""}
    if _DEGREE_CUE.search(_degree_text(text)):
        levels = [name for name, _, pat in _EDU if pat.search(_degree_text(text))]
        need = min((_EDU_RANK[n] for n in levels), default=2)
        have = _EDU_RANK.get(profile.education or "", 0)
        cov = 1.0 if have >= need else (0.5 if _SOFTENER.search(text) else 0.0)
        return {"coverage": cov, "missing": [], "how": "degree check", "via": [],
                "evidence": f"Highest degree found: {profile.education}." if profile.education else ""}
    terms = set(_content_terms(text))
    if len(terms) < 2:
        return None
    hit = terms & profile.terms
    cov = len(hit) / len(terms)
    how, ev = ("term overlap" if hit else "not found"), (_evidence_for(profile, terms=terms) if hit else "")
    sim, line, floor, span = _semantic_best(text, profile)   # embeddings (ROADMAP §6.5): wording differs, meaning matches
    sem_cov = max(0.0, min(1.0, (sim - floor) / span))
    if sem_cov > cov:
        cov, how, ev = sem_cov, "semantic match", line[:220]
    return {"coverage": cov, "missing": [], "how": how, "via": [], "evidence": ev}


def _semantic_best(text: str, profile: ResumeProfile) -> tuple[float, str, float, float]:
    """(best cosine, best resume line, credit floor, credit span) for one requirement line."""
    from .ai import embed
    emb = embed.get()
    if getattr(profile, "_line_vecs", None) is None or profile._line_vecs[0] != emb.name:
        lines = [ln for ln, _ in profile.lines if len(ln.split()) >= 4]
        object.__setattr__(profile, "_line_vecs", (emb.name, lines, emb.embed(lines)))
    _, lines, vecs = profile._line_vecs
    if not lines:
        return 0.0, "", emb.floor, emb.span
    q = emb.embed([text])[0]
    sims = [embed.cosine(q, v) for v in vecs]
    i = max(range(len(sims)), key=sims.__getitem__)
    return sims[i], lines[i], emb.floor, emb.span


def _line_coverage(text: str, profile: ResumeProfile) -> tuple[Optional[float], list[str]]:
    """Coverage 0-1 of one requirement line (None = can't judge), plus the skills it's missing."""
    a = _line_assess(text, profile)
    return (None, []) if a is None else (a["coverage"], a["missing"])


def total_from(components: dict[str, float], penalty: float = 0.0, capped: bool = False) -> int:
    """The final 0-100 score from 0-1 components (single place the weights are applied)."""
    from .calibration import apply, load
    cal = load()          # fitted logistic calibration (ROADMAP §6.6) once ≥ 300 human-labelled pairs exist
    total = (apply(components, cal) if cal else sum(W[k] * components[k] for k in W)) - penalty
    if capped:
        total = min(total, 0.45)
    return round(max(0.0, min(1.0, total)) * 100)


def weights_sentence() -> str:
    """Human-readable weights, generated from W so prompts and docs can't drift (ROADMAP D12)."""
    names = {"skills": "skills", "requirements": "requirement checklist", "role": "role fit",
             "experience": "experience", "semantic": "semantic similarity"}
    return ", ".join(f"{names[k]} {round(v * 100)}%" for k, v in W.items())


def requirement_coverage(reqs: list[dict]) -> Optional[float]:
    """Weighted mean coverage of requirement rows (must 1.0, nice 0.5); None if there are none."""
    den = sum(0.5 if r["preferred"] else 1.0 for r in reqs)
    if not den:
        return None
    return sum((0.5 if r["preferred"] else 1.0) * r["coverage"] for r in reqs) / den


def score_job(job: dict, profile: ResumeProfile, idf: Optional[dict[str, float]] = None,
              location_ok: Optional[bool] = None) -> dict:
    desc = job.get("description") or ""
    title = job.get("title") or ""
    req_text, pref_text = split_requirements(desc)
    # ROADMAP D5: skills the posting explicitly says are *not* needed are excluded
    req_skills, neg_req = sk.extract_posting_skills(req_text + "\n" + title)   # title counts as a requirement too
    pref_skills, neg_pref = sk.extract_posting_skills(pref_text)
    pref_skills -= req_skills
    negated = sorted((neg_req | neg_pref) - req_skills - pref_skills)

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

    from .ontology import credit
    credits = {s: credit(s, profile.skills, profile.implied) for s in weights}
    matched = sorted(s for s in weights if credits[s][0] >= 1.0)
    missing = sorted(s for s in weights if credits[s][0] < 1.0)
    related = [{"skill": s, "via": credits[s][2], "credit": credits[s][0], "how": credits[s][1]}
               for s in sorted(weights) if credits[s][1] in ("implied", "related")]
    if weights:
        skill_score = sum(weights[s] * credits[s][0] for s in weights) / sum(weights.values())
        if keyword_mode and (matched_kw or missing_kw):
            kw_score = len(matched_kw) / (len(matched_kw) + len(missing_kw))
            skill_score = (skill_score * len(weights) + kw_score * 3) / (len(weights) + 3)
    elif keyword_mode and (matched_kw or missing_kw):
        skill_score = len(matched_kw) / (len(matched_kw) + len(missing_kw))
    else:
        skill_score = 0.0

    # requirement lines
    reqs = []
    num = den = 0.0
    # verified AI-extracted requirements (Phase 3 extractor) replace the rule-based lines when present
    ai_reqs = (job.get("features") or {}).get("requirements")
    lines = ([(r["text"], bool(r["preferred"])) for r in ai_reqs] if ai_reqs else
             requirement_lines(desc))          # computed once per job (ROADMAP D14)
    from . import gates as gates_mod
    detected = gates_mod.detect(desc, title)
    for text, preferred in lines:
        if detected and gates_mod.is_gate_line(text, detected):
            continue                         # stated gates are pass/fail/unknown, not score (ROADMAP §6.3)
        a = _line_assess(text, profile)
        if a is None:
            continue
        cov = a["coverage"]
        w = 0.5 if preferred else 1.0
        num += w * cov
        den += w
        reqs.append({"id": f"r{len(reqs) + 1}", "text": text, "preferred": preferred, "coverage": round(cov, 2),
                     "missing": a["missing"], "how": a["how"], "via": a["via"], "evidence": a["evidence"],
                     "status": "met" if cov >= 0.75 else "partial" if cov >= 0.35 else "missing"})
    req_score = num / den if den else skill_score

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

    sem_raw = semantic_similarity(profile.text, desc, idf) if desc else 0.0
    sem_score = min(1.0, sem_raw / 0.30)

    blockers: list[str] = []
    penalty = 0.0
    edu_req, edu_strict, _ = required_education(lines)
    if edu_req and _EDU_RANK[edu_req] > _EDU_RANK.get(profile.education or "", 0):
        if edu_strict:
            blockers.append(f"Requires a {edu_req} degree; none found on your resume.")
            penalty += 0.08
        else:
            blockers.append(f"Prefers a {edu_req} degree (or equivalent experience); none found on your resume.")
            penalty += 0.02
    if req_yrs and not inferred and profile.years and profile.years < 0.6 * req_yrs:
        blockers.append(f"Asks for {req_yrs:.0f}+ years of experience; your resume shows about {profile.years:.0f}.")
    required_missing = sorted(s for s in req_skills if credits.get(s, (0,))[0] < 1.0)
    edu_line = next((t for t, _ in lines if edu_req and _DEGREE_CUE.search(_degree_text(t))), "")
    job_gates = gates_mod.evaluate(
        detected, profile.text, profile.eligibility, job.get("location", ""), location_ok,
        {"required": edu_req, "strict": edu_strict, "need_rank": _EDU_RANK.get(edu_req or "", 0),
         "have_rank": _EDU_RANK.get(profile.education or "", 0), "text": edu_line})
    low_conf = len(desc) < 80 or (not weights and not keyword_mode and not reqs)
    capped = len(desc) < 80        # title-only: can't judge skills fairly
    components = {"skills": skill_score, "requirements": req_score, "role": t_score,
                  "experience": e_score, "semantic": sem_score}
    return {
        "id": job["id"], "title": title, "company": job.get("company", ""),
        "location": job.get("location", ""), "url": job.get("url", ""), "posted": job.get("posted", ""),
        "source": job.get("source", ""), "sources": job.get("sources") or [job.get("source", "")],
        "salary": job.get("salary", ""), "remote": job.get("remote"),
        "score": total_from(components, penalty, capped),
        "components": {k: round(v * 100) for k, v in components.items()},
        "penalty": penalty, "capped": capped,
        "matched_skills": matched, "missing_skills": missing, "required_missing": required_missing,
        "related_skills": related, "gates": job_gates,
        "gates_failed": [g["label"] for g in job_gates if g["status"] == "fail"],
        "matched_keywords": matched_kw, "missing_keywords": missing_kw, "negated_skills": negated,
        "requirements": reqs, "requirements_met": sum(1 for r in reqs if r["status"] == "met"),
        "blockers": blockers, "education_required": edu_req, "education_strict": edu_strict,
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
    blockers: Counter = Counter()
    for r in results:
        for b in r.get("blockers", []):
            blockers[re.sub(r"\d+\+? years.*about \d+", "N+ years of experience (more than your resume shows)", b)] += 1
    by_source: Counter = Counter(r.get("source") or "unknown" for r in results)
    return {
        "job_count": n,
        "avg_score": round(sum(scores) / n) if n else 0,
        # qualifying = score ≥ threshold AND no failed gate (ROADMAP §6.3); gates are reported separately
        "qualifying": sum(1 for r in results if r["score"] >= threshold and not r.get("gates_failed")),
        "score_qualifying": sum(1 for s in scores if s >= threshold),
        "gate_failed": sum(1 for r in results if r["score"] >= threshold and r.get("gates_failed")),
        "gate_breakdown": dict(Counter(g for r in results if r["score"] >= threshold for g in set(r.get("gates_failed") or []))),
        "gate_unknown": dict(Counter(g["label"] for r in results for g in r.get("gates") or [] if g["status"] == "unknown")),
        "threshold": threshold,
        "distribution": buckets,
        "resume_skills": sorted(profile.skills),
        "resume_years": profile.years,
        "resume_education": profile.education,
        "skill_gaps": [
            {"skill": s, "category": sk.category_of(s), "jobs": c, "pct": round(100 * c / n) if n else 0}
            for s, c in gap.most_common(15)
        ],
        "skill_strengths": [
            {"skill": s, "category": sk.category_of(s), "jobs": c, "pct": round(100 * c / n) if n else 0}
            for s, c in owned.most_common(12) if c > 0
        ],
        "unused_skills": sorted(s for s in profile.skills if s not in in_demand_total),
        "common_blockers": [{"text": t, "jobs": c} for t, c in blockers.most_common(5)],
        "by_source": dict(by_source),
    }

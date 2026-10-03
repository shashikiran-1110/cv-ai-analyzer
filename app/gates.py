"""Hard requirements as gates (ROADMAP §6.3): pass / fail / unknown, reported separately from the score.

A gate never changes the score. "You qualify" means score ≥ threshold *and* no failed gate, and the summary says how
many more jobs would qualify but fail a gate (sponsorship ×5, clearance ×2…). "unknown" is used whenever the resume
and the user's eligibility answers can't settle it, so we never claim a fail we can't back up.
"""
from __future__ import annotations

import re
from typing import Optional

from .ontology.packs import LICENSES

_NO_SPONSOR = re.compile(r"\b(?:no|not|unable to|cannot|can't|will not|won't|do not|does not|don't)\s+(?:offer\s+|provide\s+)?"
                         r"(?:visa\s+)?sponsor(?:ship)?\b|\bwithout\s+(?:the\s+need\s+for\s+)?(?:visa\s+)?sponsorship\b|"
                         r"\bsponsorship\s+(?:is\s+)?not\s+(?:available|offered|provided)\b", re.I)
_AUTH = re.compile(r"\b(?:legally\s+)?(?:authori[sz]ed|eligible|entitled|right)\s+to\s+work\s+in\s+(?:the\s+)?"
                   r"(US|U\.S\.|USA|United States|UK|U\.K\.|United Kingdom|EU|European Union|Canada|Australia|Germany|"
                   r"India|Ireland|Netherlands|France|Singapore|New Zealand)\b", re.I)
_CITIZEN = re.compile(r"\b(?:must be|only)\s+(?:a\s+)?(US|U\.S\.|UK|British|Canadian|Australian)\s+citizens?\b", re.I)
_CLEARANCE = re.compile(r"\b(TS/SCI|top secret|secret|SC|DV|NV1|NV2|baseline|public trust)\s+(?:security\s+)?clearance\b|"
                        r"\bsecurity clearance\b|\bclearance\s+(?:is\s+)?required\b", re.I)
_CLEAR_RESUME = re.compile(r"\b(TS/SCI|top secret|secret|SC|DV|NV1|NV2|baseline|public trust)\b[^.\n]{0,30}\bclearance\b|"
                           r"\b(?:active|current|held|hold)\b[^.\n]{0,20}\bclearance\b", re.I)
_LANG_NAMES = ("English|German|French|Spanish|Italian|Portuguese|Dutch|Polish|Swedish|Danish|Norwegian|Finnish|"
               "Japanese|Mandarin|Chinese|Cantonese|Korean|Arabic|Hebrew|Hindi|Russian|Turkish|Greek|Czech")
_LANG_REQ = re.compile(rf"\b(?:fluent|fluency|native|proficient|proficiency|business[- ]level|professional)\s+(?:in\s+)?"
                       rf"(?:(?:written|spoken|and|or|both|level|working)\s+)*({_LANG_NAMES})\b|"
                       rf"\b({_LANG_NAMES})\s+(?:\(?(?:C1|C2|B2)\)?\s+)?(?:is\s+)?(?:required|essential|mandatory|a must)\b|"
                       rf"\b({_LANG_NAMES})[- ]speaking\b", re.I)
_PREFERRED = re.compile(r"\b(?:a plus|nice to have|preferred|bonus|advantage|desirable|ideally)\b", re.I)
_ONSITE = re.compile(r"\b(?:on-?site|in[- ]office|in the office)\b[^.\n]{0,40}\b(?:\d\s*days|full[- ]time|required|only|"
                     r"5 days|every day)\b|\bfully on-?site\b|\b(?:must|required to)\s+(?:be\s+)?(?:located|based|live)\s+"
                     r"(?:in|within|near)\b|\brelocation (?:is )?required\b|\bno remote\b|\bnot (?:a )?remote\b", re.I)
_LANG_SECTION = re.compile(r"^\W*languages?\W*$|\blanguages?\s*:", re.I | re.M)
_COUNTRY_NORM = {"us": "US", "u.s.": "US", "usa": "US", "united states": "US", "uk": "UK", "u.k.": "UK",
                 "united kingdom": "UK", "british": "UK", "eu": "EU", "european union": "EU", "canadian": "Canada",
                 "australian": "Australia"}

GATE_LABELS = {"authorization": "work authorization", "clearance": "security clearance", "license": "licence",
               "language": "language", "onsite": "on-site location", "degree": "degree"}


def _country(name: str) -> str:
    return _COUNTRY_NORM.get(name.lower(), name.title() if len(name) > 3 else name.upper())


def _sentence(text: str, m: re.Match) -> str:
    """The clause stating a gate (split on newlines, sentence ends and semicolons)."""
    start = max(text.rfind(sep, 0, m.start()) for sep in ("\n", ". ", "; "))
    ends = [e for e in (text.find(sep, m.end()) for sep in ("\n", ". ", "; ")) if e != -1]
    return re.sub(r"\s+", " ", text[start + 1:min(ends or [len(text)])]).strip(" -•*;.")[:220]


def is_gate_line(line: str, detected: list[dict]) -> bool:
    """True if a requirement line just states a gate (scored as a gate, not as coverage)."""
    norm = re.sub(r"\s+", " ", line).strip(" -•*").lower()
    return any(norm and (norm in g["text"].lower() or g["text"].lower() in norm) for g in detected if g["type"] != "onsite")


def detect(description: str, title: str = "") -> list[dict]:
    """Gate requirements stated in a posting (each with the sentence that states it)."""
    text = description or ""
    gates: list[dict] = []
    for m in _AUTH.finditer(text):
        gates.append({"type": "authorization", "need": _country(m.group(1)), "text": _sentence(text, m),
                      "no_sponsorship": bool(_NO_SPONSOR.search(text))})
        break
    else:
        m = _CITIZEN.search(text)
        if m:
            gates.append({"type": "authorization", "need": _country(m.group(1)), "text": _sentence(text, m),
                          "no_sponsorship": True, "citizen": True})
        elif (m := _NO_SPONSOR.search(text)):
            gates.append({"type": "authorization", "need": "", "text": _sentence(text, m), "no_sponsorship": True})
    m = _CLEARANCE.search(text + "\n" + title)
    if m and not _PREFERRED.search(_sentence(text, m) if m.start() < len(text) else ""):
        level = m.group(1) or "Security"
        gates.append({"type": "clearance", "need": level.upper() if len(level) <= 6 else level.title(),
                      "text": _sentence(text + "\n" + title, m)})
    for pat, name in LICENSES.items():
        m = re.search(pat, text, re.I)
        if m and not _PREFERRED.search(_sentence(text, m)):
            gates.append({"type": "license", "need": name, "pattern": pat, "text": _sentence(text, m)})
    seen_lang = set()
    for m in _LANG_REQ.finditer(text):
        lang = next(g for g in m.groups() if g).title()
        if lang in seen_lang or _PREFERRED.search(_sentence(text, m)):
            continue
        seen_lang.add(lang)
        gates.append({"type": "language", "need": lang, "text": _sentence(text, m)})
    m = _ONSITE.search(text)
    if m:
        gates.append({"type": "onsite", "need": "", "text": _sentence(text, m)})
    return gates


def evaluate(gates: list[dict], resume_text: str, eligibility: Optional[dict], job_location: str = "",
             location_ok: Optional[bool] = None, degree: Optional[dict] = None) -> list[dict]:
    """Decide each gate: pass / fail / unknown, with a reason the user can act on."""
    el = eligibility or {}
    out = []
    for g in gates:
        status, reason = "unknown", ""
        t = g["type"]
        if t == "authorization":
            countries = {c.upper() for c in el.get("work_countries") or []}
            needs = el.get("needs_sponsorship")
            need = (g.get("need") or "").upper()
            if need and countries:
                if need in countries or (need == "EU" and countries & {"EU", "GERMANY", "FRANCE", "IRELAND", "NETHERLANDS"}):
                    status, reason = "pass", f"You're authorised to work in {g['need']}."
                elif g.get("no_sponsorship") or needs is not False:
                    status, reason = "fail", f"Requires the right to work in {g['need']}" + (" and no sponsorship is offered." if g.get("no_sponsorship") else ".")
            elif g.get("no_sponsorship") and needs is not None:
                status = "fail" if needs else "pass"
                reason = "No visa sponsorship offered; you said you need it." if needs else "No sponsorship needed."
            if status == "unknown":
                reason = "Set your work authorisation on your profile to check this."
        elif t == "clearance":
            held = el.get("clearance") or ""
            if held or _CLEAR_RESUME.search(resume_text):
                status, reason = "pass", f"Clearance found: {held or _CLEAR_RESUME.search(resume_text).group(0)}."
            else:
                status, reason = "fail", "No security clearance on your resume or profile."
        elif t == "license":
            mine = " ".join(el.get("licenses") or [])
            if re.search(g["pattern"], resume_text, re.I) or (mine and re.search(g["pattern"], mine, re.I)) or \
                    any(g["need"].lower() in x.lower() for x in el.get("licenses") or []):
                status, reason = "pass", f"{g['need']} found."
            else:
                status, reason = "fail", f"{g['need']} isn't on your resume. Add it (or to your profile) if you hold it."
        elif t == "language":
            langs = {x.lower() for x in el.get("languages") or []}
            if g["need"].lower() in langs or re.search(rf"\b{g['need']}\b", resume_text, re.I):
                status, reason = "pass", f"{g['need']} found."
            elif g["need"] == "English":
                status, reason = "pass", "Resume is written in English."
            elif langs or _LANG_SECTION.search(resume_text):
                status, reason = "fail", f"{g['need']} isn't in your languages."
            else:
                reason = f"Add your languages to your profile to check {g['need']}."
        elif t == "onsite":
            if location_ok:
                status, reason = "pass", f"On-site in {job_location or 'the listed location'}, which matches your search."
            elif el.get("relocate") is True:
                status, reason = "pass", "On-site; you're open to relocating."
            elif el.get("relocate") is False or el.get("remote_only"):
                status, reason = "fail", f"On-site in {job_location or 'another location'}; you said you won't relocate."
            else:
                reason = f"On-site in {job_location or 'the listed location'}; set your relocation preference to check."
        out.append({**{k: v for k, v in g.items() if k != "pattern"}, "status": status, "reason": reason,
                    "label": GATE_LABELS[t]})
    if degree and degree.get("required") and degree.get("strict"):
        ok = degree.get("have_rank", 0) >= degree.get("need_rank", 0)
        out.append({"type": "degree", "need": degree["required"], "text": degree.get("text", ""),
                    "status": "pass" if ok else "fail", "label": GATE_LABELS["degree"],
                    "reason": f"Requires a {degree['required']} degree" + ("." if ok else "; none found on your resume (no 'or equivalent').")})
    return out

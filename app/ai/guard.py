"""Safety & guardrails (ROADMAP §8.9).

- `verify_claim`: generated resume text may only use facts the profile (or the user's own answers) already contains:
  no new skills/tools, employers, titles, degrees or dates; numbers must come from the source or be `[placeholders]`.
- `numbers_supported`: every number in an AI answer must appear in the tool output it was given (coach).
- `sanitize_untrusted`: neutralise common prompt-injection phrasing inside untrusted text shown to a model.
"""
from __future__ import annotations

import re

from .. import matcher
from .. import skills as sk

_INJECTION = re.compile(
    r"(?i)\b(ignore|disregard|forget)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all)\b[^.\n]{0,40}"
    r"\b(instructions?|prompts?|rules?|messages?)\b|"
    r"\byou are now\b|\bsystem prompt\b|\bnew instructions?\b\s*:|\bact as (?:an?|the)\b|<\s*/?\s*system\s*>")
_NUM = re.compile(r"(?<![\w\[])(?:[$£€]\s?)?\d+(?:[.,]\d+)*\s*(?:%|x\b|k\b|m\b|bn\b|\+)?", re.I)
_PLACEHOLDER = re.compile(r"\[[^\]]{1,40}\]")
_YEAR = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
_DEGREE = re.compile(r"\b(ph\.?d|doctorate|master'?s|msc|m\.s\.|mba|bachelor'?s|bsc|b\.s\.|b\.a\.|degree)\b", re.I)
_TITLE_WORDS = re.compile(r"\b(senior|lead|principal|staff|head of|director|manager|vp|chief|architect)\b", re.I)
_PROPER = re.compile(r"(?<![.!?]\s)(?<!^)\b([A-Z][a-zA-Z0-9&]+(?:\s+[A-Z][a-zA-Z0-9&]+)*)\b")
_COMMON_CAPS = {"I", "The", "A", "An", "Led", "Built", "Designed", "Developed", "Managed", "Created", "Delivered",
                "Improved", "Reduced", "Increased", "Owned", "Drove", "Launched", "Implemented", "Automated", "Migrated",
                "Mentored", "Partnered", "Collaborated", "Established", "Streamlined", "Optimized", "Optimised",
                "Shipped", "Scaled", "Spearheaded", "Architected", "Analyzed", "Analysed", "Worked", "Supported",
                "Prepared", "Ran", "Wrote", "Introduced", "Coordinated", "Trained", "Maintained", "Defined", "Used"}


def echoes_instructions(output: str, instructions: str, run: int = 7) -> bool:
    """True if `output` repeats any `run`-word stretch of `instructions` (prompt leak via injected text)."""
    words = re.findall(r"[a-z']+", instructions.lower())
    out = " ".join(re.findall(r"[a-z']+", output.lower()))
    return any(" ".join(words[i:i + run]) in out for i in range(max(0, len(words) - run + 1)))


def sanitize_untrusted(text: str) -> str:
    return _INJECTION.sub("[removed instruction-like text]", text)


def _numbers(text: str) -> set[str]:
    clean = _PLACEHOLDER.sub(" ", text)
    return {re.sub(r"[\s,$£€]", "", m.group(0)).rstrip("+").lower() for m in _NUM.finditer(clean)
            if re.search(r"\d", m.group(0))}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


def verify_claim(new_text: str, profile_text: str, source_text: str = "", user_facts: str = "") -> list[str]:
    """Violations (empty list = safe). `source_text` is the bullet being rewritten; `user_facts` the user's answers."""
    allowed = "\n".join([profile_text, source_text, user_facts])
    allowed_norm = _norm(allowed)
    out: list[str] = []
    new_skills = sk.extract_skills(new_text) - sk.extract_skills(allowed)
    from ..ontology import implied_by
    new_skills -= set(implied_by(sk.extract_skills(allowed)))         # Django on the resume ⇒ Python is fine
    for s in sorted(new_skills):
        out.append(f"Adds the skill “{s}”, which isn't on your resume.")
    allowed_nums = _numbers(source_text + "\n" + user_facts)
    for n in sorted(_numbers(new_text) - allowed_nums):
        if _YEAR.fullmatch(n):
            continue                                    # reported as a date below
        out.append(f"Uses the number “{n}”, which isn't in the original bullet or your answers. Use a [placeholder].")
    for y in sorted(set(_YEAR.findall(new_text)) - set(_YEAR.findall(allowed))):
        out.append(f"Adds the date “{y}”.")
    if _DEGREE.search(new_text) and not _DEGREE.search(allowed):
        out.append("Mentions a degree that isn't on your resume.")
    for w in {m.group(0).lower() for m in _TITLE_WORDS.finditer(new_text)}:
        if w not in allowed_norm:
            out.append(f"Adds the title word “{w}”, which isn't on your resume.")
    for m in _PROPER.finditer(_PLACEHOLDER.sub(" ", new_text)):
        name = m.group(1)
        first = name.split()[0]
        if first in _COMMON_CAPS or len(name) < 3 or sk.canonical(name) or _norm(name) in allowed_norm:
            continue
        allowed_words = set(re.findall(r"[a-z0-9&]+", allowed_norm))
        words = [p for p in name.split() if not re.fullmatch(r"[A-Z]{2,}s?", p)]   # acronyms: DAGs, APIs
        if all(part.lower() in allowed_words for part in words):
            continue                                    # every word already on the resume ("SQL ETL", "Acme Analytics")
        out.append(f"Names “{name}”, which isn't on your resume (new employer, product or credential?).")
    return out


def numbers_supported(answer: str, evidence: str) -> list[str]:
    """Numbers in `answer` that don't appear in `evidence` (tool outputs + user messages)."""
    ev = _numbers(evidence)
    ev |= {n.rstrip("%") for n in ev}
    body = re.sub(r"(?m)^\s*\d{1,2}[.)]\s", " ", answer)          # list numbering isn't a claim
    return sorted(n for n in _numbers(body) if n not in ev and n.rstrip("%") not in ev and n.rstrip("%"))


def content_terms(text: str) -> set[str]:
    return set(matcher._content_terms(text))

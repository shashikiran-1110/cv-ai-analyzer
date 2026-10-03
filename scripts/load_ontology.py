"""Import alternative skill labels from ESCO and/or O*NET into the matcher's ontology (ROADMAP §6.4).

Download the files yourself (both are free; see THIRD_PARTY.md for licences), then:

    python scripts/load_ontology.py --esco path/to/skills_en.csv [--esco-relations path/to/skillSkillRelations_en.csv]
    python scripts/load_ontology.py --onet path/to/Technology\\ Skills.txt

Only labels that map onto a skill already in the taxonomy are imported (precision first): an ESCO concept is linked
when its preferred label or an alternative label equals one of our canonical names/aliases. Its other alternative
labels then become extra aliases. ESCO "related" skill relations between two linked concepts become related-skill
pairs (partial credit). Output: app/data/ontology/{aliases,related}.json, read at start-up.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import skills as sk  # noqa: E402
from app.ontology import DATA  # noqa: E402

_OK_ALIAS = re.compile(r"^[a-z0-9][a-z0-9 +#./&-]{1,40}$")


def _labels(row: dict) -> list[str]:
    alts = re.split(r"\n|\|", row.get("altLabels") or "")
    return [x.strip().lower() for x in [row.get("preferredLabel", ""), *alts] if x and x.strip()]


def from_esco(skills_csv: Path, relations_csv: Path | None) -> tuple[dict[str, list[str]], list[list[str]]]:
    aliases: dict[str, set[str]] = {}
    uri_to_canon: dict[str, str] = {}
    with skills_csv.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            labels = _labels(row)
            canon = next((sk.canonical(l) for l in labels if sk.canonical(l)), None)
            if not canon:
                continue
            uri_to_canon[row.get("conceptUri", "")] = canon
            for l in labels:
                if _OK_ALIAS.match(l) and not sk.canonical(l) and len(l.split()) <= 5:
                    aliases.setdefault(canon, set()).add(l)
    related: set[tuple[str, str]] = set()
    if relations_csv:
        with relations_csv.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                a, b = uri_to_canon.get(row.get("originalSkillUri", "")), uri_to_canon.get(row.get("relatedSkillUri", ""))
                if a and b and a != b and (row.get("relationType") or "").lower() in ("optional", "related", ""):
                    related.add(tuple(sorted((a, b))))
    return {k: sorted(v) for k, v in aliases.items()}, [list(p) for p in sorted(related)]


def from_onet(tech_txt: Path) -> dict[str, list[str]]:
    """O*NET 'Technology Skills' (tab-separated: O*NET-SOC Code, Example, Commodity Code, Commodity Title, …)."""
    aliases: dict[str, set[str]] = {}
    with tech_txt.open(encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            example = (row.get("Example") or "").strip().lower()
            canon = sk.canonical(example) or next((sk.canonical(w) for w in re.split(r"[ /]", example) if sk.canonical(w)), None)
            if canon and _OK_ALIAS.match(example) and not sk.canonical(example):
                aliases.setdefault(canon, set()).add(example)
    return {k: sorted(v) for k, v in aliases.items()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--esco", type=Path)
    ap.add_argument("--esco-relations", type=Path)
    ap.add_argument("--onet", type=Path)
    ap.add_argument("--out", type=Path, default=DATA)
    a = ap.parse_args(argv)
    if not (a.esco or a.onet):
        ap.error("give --esco and/or --onet")
    aliases: dict[str, set[str]] = {}
    related: list[list[str]] = []
    if a.esco:
        al, related = from_esco(a.esco, a.esco_relations)
        for k, v in al.items():
            aliases.setdefault(k, set()).update(v)
    if a.onet:
        for k, v in from_onet(a.onet).items():
            aliases.setdefault(k, set()).update(v)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "aliases.json").write_text(json.dumps({k: sorted(v) for k, v in sorted(aliases.items())}, indent=1))
    (a.out / "related.json").write_text(json.dumps(related, indent=1))
    print(f"{sum(len(v) for v in aliases.values())} aliases for {len(aliases)} skills, {len(related)} related pairs → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

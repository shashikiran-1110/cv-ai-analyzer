# Match set (ROADMAP §7.1–7.2) — needs human labels

`pairs.jsonl` holds labelled resume–job pairs. The `match` suite in `python -m eval.run` scores only pairs with
`"reviewed": true`, and reports Spearman ρ (score vs label), precision/recall/F1 for "qualified" at score ≥ 60, and
expected calibration error. Phase 1 needs **≥ 300 reviewed pairs across ≥ 6 occupations** before any weight is fitted.

This set is deliberately empty in the repository: labels must not be invented. Build it like this:

1. **Collect** resumes (synthetic ones generated per occupation and clearly marked `"synthetic": true`, plus consented,
   anonymized real ones) and postings (from the job cache or pasted). Cover ≥ 10 occupations outside software
   (nursing, accounting, logistics, teaching, sales, legal, design, operations, customer support, trades).
2. **Pre-label** with a strong model: `python -m eval.labeling.prelabel pairs_unlabelled.jsonl out.jsonl`
   (uses your AI key from `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`; quotes are verified against the resume).
3. **Review**: a human checks 100 % of items where two models disagree, plus a random 20 %, sets `label`,
   per-requirement statuses, and `"reviewed": true`. Record reviewer ids.
4. **Agreement**: compute Cohen's κ on the 4-level label for the double-annotated subset; target κ ≥ 0.6.

## Schema (one JSON object per line)

```json
{"id": "nurse-03__job-17", "occupation": "nursing", "synthetic": true,
 "resume": "…full resume text…", "job_title": "Registered Nurse", "job_description": "…",
 "label": "strong | possible | stretch | no",
 "requirements": [{"text": "Active RN license", "status": "met | partial | missing", "quote": "…"}],
 "prelabel": {"model": "…", "label": "…"}, "reviewed": true, "reviewer": "initials"}
```

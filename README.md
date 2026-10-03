# CV Match Analyzer

Search real LinkedIn job postings (title, location, number of posts, time range), upload your PDF resume, and see:

- how many of those jobs you'd **qualify** for (% and count, with an adjustable threshold),
- a **per-job match score** (skills 60% · role fit 25% · experience 15%) with matched / missing skills,
- your **strengths**, **areas to improve**, and a ranked list of **skills to work on**.

## Run

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload      # http://127.0.0.1:8000
```

Optional AI-written advice: `export OPENAI_API_KEY=...` (model via `OPENAI_MODEL`, default `gpt-5.6-luna`), or `ANTHROPIC_API_KEY` / `CLAUDE_MODEL` instead. `AI_PROVIDER` forces one when both are set. Without a key the app uses its built-in local analysis. Scores are always computed locally and deterministically; the key only affects the written advice, and the UI asks before sending resume text to the API.

## How it works

| Piece | File |
|---|---|
| LinkedIn public guest-endpoint scraper (paging, retries, progress) | `app/linkedin.py` |
| PDF text + experience-years extraction | `app/resume.py` |
| Skill taxonomy (~250 skills, whole-word matching) | `app/skills.py` |
| Scoring & aggregation | `app/matcher.py` |
| Local + OpenAI/Claude insights (falls back on any failure) | `app/insights.py` |
| API + static UI | `app/main.py`, `app/static/` |

## Notes & limits

- LinkedIn data comes from its **unauthenticated public job pages**. LinkedIn may rate-limit, block datacenter IPs, or change markup, and its terms restrict automated access. Keep volumes small and personal. Errors are surfaced in the UI.
- Postings without a loadable description are flagged and their score is capped (rough estimate).
- Scoring is a keyword/skill heuristic, not a hiring decision. Scanned (image-only) PDFs aren't supported (no OCR).
- Searches are held in memory for 1 hour; resumes are never written to disk.

## Tests

```bash
python -m pytest
```

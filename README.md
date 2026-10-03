# CV Match Analyzer

Search real LinkedIn postings (title, location, count, time range, experience level, job type, workplace), upload or paste your resume, and see:

- how many of those jobs you'd **qualify** for (% and count, adjustable threshold),
- a **per-job match score** (skills 60% · role fit 25% · experience 15%) with matched / missing skills,
- your **strengths**, **areas to improve** and a ranked list of **skills to work on**,
- a **what-if** simulator: add skills you have or plan to learn and instantly see how many more jobs you'd unlock,
- an **AI assistant** (OpenAI or Anthropic, your own key): streaming chat about your resume and the jobs, plus per-job cover letter, resume tailoring, interview prep and a 30-day gap plan.

## Run

```bash
./run.sh            # installs deps, builds the React UI, serves http://localhost:8000
```

No LinkedIn access or API key handy? Try the full UI with canned data:

```bash
python scripts/demo_server.py     # http://localhost:8765  (AI settings: OpenAI, key `sk-good`)
```

Development: `uvicorn app.main:app --reload` plus `cd frontend && npm run dev` (http://localhost:5173, proxies `/api`).

## AI keys

Click **AI settings** (top right), choose OpenAI or Anthropic, paste your key and press **Verify & save**. Verification only reads the model's metadata, so it is instant, free, and tells a bad key apart from a bad model name (default model `gpt-5.6-luna`, editable).

- The key lives in your browser (`sessionStorage`, or `localStorage` if you tick "remember") and is sent only as headers on AI requests. The server never stores or logs it and scrubs it from error messages.
- Alternatively set `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` on the server (see `.env.example`).
- Scores are always computed locally and deterministically; AI only writes advice, chat and documents.
- Resume text is sent to your chosen provider only when you use an AI feature.

## Architecture

| Piece | Where |
|---|---|
| FastAPI app, analysis sessions, SSE streaming | `app/main.py` |
| LinkedIn public guest-endpoint scraper (paging, filters, retries, progress) | `app/linkedin.py` |
| OpenAI/Anthropic client: verify, complete, stream | `app/llm.py` |
| Assistant prompts and context | `app/assistant.py`, `app/insights.py` |
| PDF text + experience-years extraction | `app/resume.py` |
| Skill taxonomy and scoring | `app/skills.py`, `app/matcher.py` |
| React + TypeScript + Vite UI | `frontend/` |

## Notes & limits

- LinkedIn data comes from its **unauthenticated public job pages**. LinkedIn may rate-limit, block datacenter IPs, or change its markup, and its terms restrict automated access. Keep volumes small and personal. Errors are surfaced in the UI.
- Postings without a loadable description are flagged and their score is capped.
- Scoring is a skill/keyword heuristic, not a hiring decision. Scanned (image-only) PDFs aren't supported (no OCR); paste text instead.
- Searches and analyses are held in memory for 1 hour; resumes are never written to disk.

## Tests

```bash
python -m pytest            # backend
cd frontend && npm run build   # typecheck + production build
```

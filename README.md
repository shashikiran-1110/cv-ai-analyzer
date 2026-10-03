# CV Match Analyzer

Upload your CV, describe the role, and the app collects real postings from **LinkedIn, public job boards, company
career sites (9 ATS platforms), USAJOBS and job URLs**, scores your resume against **every requirement** of every
posting, and tells you:

- how many jobs you **qualify** for (score ≥ threshold *and* no failed hard requirement), with the count and %,
- per job: an explainable score, a **requirement matrix** (requirement ↔ status ↔ evidence from your resume ↔ how it
  was decided, highlighted in the posting) and **hard requirements** (work authorisation, clearance, licences,
  languages, on-site, strict degree) shown as pass / fail / unknown, separately from the score,
- **strengths**, **areas to improve** and ranked **skills to work on**, plus a what-if simulator,
- optional AI (OpenAI or Anthropic, **your key**, kept in your browser):
  - **deep verification**: requirement-by-requirement with resume quotes the server checks,
  - **Tailoring Agent**: proposes resume edits through a claim guard (no invented skills, employers, titles, dates or
    numbers), shows the projected score, lets you accept/edit each one, exports a **.docx**,
  - **Search Planner**, **Career Coach** (uses tools; numbers it can't back up are flagged), **Interview Coach**,
    cover letters, market summaries.

Also: profile review (fix what the parser read), application **tracker** (kanban), **watches** (saved searches
with daily/weekly digests), **market insights**, a **browser extension** ("score this job" on any page), optional
magic-link **accounts**. The plan and its status are in [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Run

```bash
./run.sh            # installs deps, builds the UI, serves http://localhost:8000
```

Try everything offline with every external service faked (job portals, Wellfound, OpenAI, email):

```bash
python scripts/demo_server.py     # http://localhost:8765 · AI key `sk-good` · Adzuna App ID `demo`
```

Docker (API + Postgres): `cp .env.example .env && docker compose up -d --build` → http://localhost:8000.
Every setting is documented in [`.env.example`](.env.example).

Development: `uvicorn app.main:app --reload` and `cd frontend && npm run dev` (http://localhost:5173, proxies `/api`).

## Job sources

| Source | How | Notes |
|---|---|---|
| LinkedIn | public guest job pages | largest volume; may rate-limit or ask for sign-in (detected and reported) |
| Remotive, RemoteOK, Jobicy, Himalayas, Arbeitnow, The Muse | official public APIs | board feeds cached 15 min |
| Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee, Personio, Teamtailor, Workday | companies' public career-site feeds | type a company name and **Find** resolves its board |
| Adzuna, USAJOBS | official APIs, free key | your key, sent only with the search |
| Job URLs | the page's schema.org `JobPosting` data | Wellfound, company career pages, LinkedIn links… |
| Browser extension | reads the page *you* are viewing | works where sites block bots (LinkedIn, Indeed, Wellfound) |
| Paste jobs / Sample jobs | | always work, even with no network |

Every source runs concurrently and fails independently; results are filtered (title relevance incl. the planner's
alternative titles, location, recency, workplace, type, seniority), **deduplicated across sources**, ranked and
spread fairly so one source can't crowd out the rest.

## Matching (deterministic, explainable, name-blind)

`score = 40% skills + 20% requirements + 15% role fit + 15% experience + 10% semantic similarity`. Requirements come
from the posting's own lines (or, with AI, an extractor whose every item must be found in the posting). Skills use a
~270-skill taxonomy with context rules, negation, degree context, domain packs for non-tech roles, and an ontology
(Django ⇒ Python counts in full; MySQL for PostgreSQL counts as related, partial). Experience is counted in months
from dated roles; you can correct anything on the profile page. Names, pronouns and contact details are removed
before matching. Hard requirements never change the score; they decide "qualifies". When ≥ 300 human-labelled
pairs exist, `python -m eval.fit_calibration` fits a logistic calibration the engine then uses.

## Privacy

Keys stay in your browser and are sent only with AI requests; the server never stores or logs them. Resumes,
reports and searches are kept 7 days for anonymous use (365 when signed in), and you can export or delete
everything in Settings. Job URLs go through an SSRF guard. Details: [`PRIVACY.md`](PRIVACY.md).
A server-side AI key is ignored unless `ALLOW_SERVER_KEY_ANON=true` (`run.sh` sets it, as it listens on 127.0.0.1).

## "Request failed"? Use **Menu → Connection check**

It shows, per source and AI provider, whether the **server** can reach it. Sandboxes, corporate proxies and
firewalls commonly block `www.linkedin.com` or `api.openai.com`; allow those or run the app on your own computer.

## Tests and evaluation

```bash
python -m pytest --ignore=tests/e2e     # 240 tests (API, sources, matcher, gates, agents, accounts, tracker, watches…)
TEST_DATABASE_URL=postgresql+psycopg://user@localhost/db python -m pytest --ignore=tests/e2e   # same suite on Postgres
python -m pytest tests/e2e             # Playwright: the whole UI against the demo server
python -m eval.run --check             # accuracy suites; fails on regressions (CI runs it)
cd frontend && npm run build           # typecheck + production build
```

The match-quality suite needs human-labelled resume–job pairs: see
[`eval/datasets/match/README.md`](eval/datasets/match/README.md). Live agent evals need an AI key:
`python -m eval.agents_live`.

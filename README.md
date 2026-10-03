# CV Match Analyzer

Upload your CV, describe the role (title, location, number of posts, time range, filters), and the app collects
real postings from **LinkedIn, public job boards, company career sites and job URLs**, scores your resume against
**every requirement** of every posting, and tells you:

- how many jobs you **qualify** for (count and %, adjustable threshold),
- a per-job, explainable score with a **requirement checklist**, blockers (degree, years) and missing skills,
- **strengths**, **areas to improve** and ranked **skills to work on**, plus a what-if simulator,
- optional **deep AI verification** (OpenAI or Anthropic, your key): requirement-by-requirement with resume quotes
  that the server checks, so the AI can't invent qualifications,
- an AI assistant: streaming chat, cover letters, tailored resume bullets, interview prep, 30-day gap plans.

The design is in [`docs/PLAN.md`](docs/PLAN.md).

## Run

```bash
./run.sh            # installs deps, builds the UI, serves http://localhost:8000
```

Try everything offline with every external service faked (job portals, Wellfound, OpenAI):

```bash
python scripts/demo_server.py     # http://localhost:8765 · AI key `sk-good` · Adzuna App ID `demo`
```

Development: `uvicorn app.main:app --reload` and `cd frontend && npm run dev` (http://localhost:5173, proxies `/api`).

## Job sources

| Source | How | Notes |
|---|---|---|
| LinkedIn | public guest job pages | largest volume; may rate-limit or ask for sign-in (detected and reported) |
| Remotive, RemoteOK, Jobicy, Himalayas | official public APIs | remote jobs |
| Arbeitnow | official public API | Europe (mostly Germany) + remote |
| The Muse | official public API | US-heavy, curated companies |
| Greenhouse, Lever, Ashby | companies' official job-board APIs | enter company slugs (e.g. `stripe`) |
| Adzuna | official aggregator API, free key | thousands of boards, 19 countries; shortened descriptions |
| Job URLs | the page's schema.org `JobPosting` data | Wellfound, company career pages, Workday, LinkedIn links… |
| Paste jobs / Sample jobs | | always work, even with no network |

**Wellfound** has no public API and blocks automated clients, so it isn't searched in bulk. Paste Wellfound job
links under *Job URLs* (imported when Wellfound allows it; you get a clear message when it doesn't), or paste the
posting text under *Paste jobs*.

Every source runs concurrently and fails independently; results are filtered (title relevance, location incl.
remote-in-your-country, recency, workplace, job type, seniority), **deduplicated across sources**, ranked, and
spread fairly so one source can't crowd out the rest.

## Matching (deterministic, explainable)

`score = 40% skills + 20% requirements + 15% role fit + 15% experience + 10% semantic similarity`, minus small
penalties for hard blockers. Requirement lines are extracted section-aware ("Requirements", "Nice to have",
skipping benefits/company blurb) and each is marked met / partial / missing. Skills come from a ~220-skill
taxonomy with false-positive guards ("the rest of the team" ≠ REST, "excel in" ≠ Excel). Deep AI checks blend
50/50 with the rules score; unverifiable AI claims are downgraded.

## "Request failed"? Use **Connection check**

The header's *Connection check* shows, per source and AI provider, whether the **server** can reach it. Sandboxes,
corporate proxies and firewalls commonly block `www.linkedin.com` or `api.openai.com`; allow those domains or run
the app on your own computer. Sources that work still return results, and *Paste jobs* always works.

## Privacy

AI and Adzuna keys stay in your browser and are sent only with the requests that need them; the server never
stores or logs them and redacts them from errors. Resumes are processed in memory (1-hour sessions), never written
to disk, and sent to your AI provider only when you use AI features.

## Tests

```bash
python -m pytest              # 75 backend tests (sources, matcher, AI verification, API)
cd frontend && npm run build  # typecheck + production build
```

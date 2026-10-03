# CV Match Analyzer: end-to-end plan

Goal: given a target role (title, location, count, time range, filters) and a resume, collect **as many real,
relevant postings as possible from trusted sources**, score the resume against each one **robustly and
explainably**, and tell the user how many they qualify for, why, and what to improve.

```
 ┌──────────── Setup (one screen) ───────────┐
 │ Resume (PDF / paste) → instant preview    │      ┌────────────── Report ──────────────┐
 │ Role + location + count + time + filters  │ ───▶ │ qualify N of M · per-job evidence  │
 │ Sources (LinkedIn, boards, ATS, URLs…)    │      │ strengths · gaps · what-if · AI    │
 └───────────────────────────────────────────┘      └────────────────────────────────────┘
          │                       ▲
          ▼                       │
  1 Ingest ─▶ 2 Normalize ─▶ 3 Filter/Dedupe/Rank ─▶ 4 Match v2 ─▶ 5 Deep AI verify (opt-in) ─▶ 6 Insights
```

## 1. Ingestion: source plugins (`app/sources/`)

Every source implements one interface (`fetch(query) -> list[Job]`), runs **concurrently** with its own
timeout, and **fails in isolation**: one blocked portal never fails the search. Each source reports its
status (fetched / kept / error / warning) to the UI.

| Source | Access | Why trusted | Notes |
|---|---|---|---|
| LinkedIn | public guest job pages | largest volume | rate-limits/authwall detected and reported |
| Remotive | official public API | curated remote jobs | remote only |
| RemoteOK | official public JSON | large remote board | remote only, attribution link kept |
| Arbeitnow | official public API | EU/DE + remote | |
| Jobicy | official public API | remote | |
| Himalayas | official public API | remote, structured seniority | |
| The Muse | official public API | US-heavy, curated companies | no keyword search: filtered locally |
| Greenhouse / Lever / Ashby | official job-board APIs | the companies' own ATS: the canonical posting | user lists company slugs |
| Adzuna | official API (free key) | aggregator of thousands of boards, many countries | key entered in the UI, stays in browser |
| Job URLs (Wellfound, company career pages, Workday, Indeed…) | the page's schema.org `JobPosting` JSON-LD | the publisher's own structured data | Wellfound blocks bots aggressively; when blocked we say so and offer paste |
| Paste | user-supplied | | always works |
| Sample | built-in, clearly labelled | | for trying the app |

Wellfound has no public API and actively blocks automated clients, so a "search Wellfound" scraper would be
unreliable and against its terms. Instead, Wellfound job URLs are imported one by one via the page's
structured data, with a clear message when Wellfound blocks the request.

## 2. Normalization
One `Job` shape: id, source, title, company, location, remote flag, url, posted (ISO), description (plain
text from HTML), seniority, employment type, salary, tags. HTML is converted to text keeping bullet
structure (needed for requirement extraction).

## 3. Filter, dedupe, rank
- **Relevance**: query title tokens (minus seniority/noise words, with synonyms such as engineer≈developer)
  must appear in the job title; weaker matches via tags/description are ranked lower.
- **Location**: substring/token match, plus remote jobs open to "worldwide/anywhere" or the user's region.
- **Recency**: drop postings older than the time range when a date is known.
- **Dedupe** across sources on normalized (company, title, location); keep the richest description and
  record every source it appeared on.
- **Rank** by relevance → description completeness → recency, then cut to the requested count, spread
  fairly across sources.

## 4. Matcher v2 (deterministic, explainable)
Per job, 0-100:
| Component | Weight | What it measures |
|---|---|---|
| Skills | 40% | taxonomy skills; required = 1.0, preferred ("nice to have") = 0.5, soft skills half |
| Requirements | 20% | each requirement *line* is checked: its skills owned / key terms present in resume |
| Role fit | 15% | target-role words in resume, headline weighted |
| Experience | 15% | years required (stated or inferred from seniority) vs years on resume |
| Semantic | 10% | TF-IDF cosine similarity resume ↔ posting (catches non-taxonomy overlap) |

Plus **blockers**: education level (e.g. "Master's required", none found) and explicit years shortfalls are
listed per job and apply a small penalty. Postings without description text are capped and marked low
confidence. Every number shown in the UI is traceable to matched/missing evidence.

## 5. Deep AI verification (opt-in, user's key)
For the jobs the user chooses (top N by default) the AI returns, per requirement: importance (must/nice),
status (met/partial/missing) and an **evidence quote from the resume**. The server **verifies each quote
actually exists in the resume**; unverifiable "met" claims are downgraded to partial and flagged, so the AI
can't invent qualifications. The final score blends deterministic and AI scores, both shown.

## 6. Insights, what-if, assistant
Strengths, improvement areas, ranked skills to learn; what-if re-scoring with added skills; streaming chat
and per-job documents (cover letter, tailored bullets, interview prep, 30-day plan).

## Reliability and safety
- Connection check (`/api/diagnose`) shows per-source and AI reachability so "request failed" is never a
  mystery (e.g. a firewall/sandbox blocking linkedin.com or api.openai.com).
- Retries with backoff, Retry-After, per-source timeouts, partial results with warnings.
- API keys only in the browser, sent per request, redacted from errors; resume kept in memory only.
- Every parser has fixture tests; the full UI flow is covered by a browser test against the demo server.

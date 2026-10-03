# Privacy & data inventory

| Data | Where | How long | Who can see it |
|---|---|---|---|
| Resume text, parsed profile, your corrections | server database | 7 days anonymous / 365 days signed in (`ANON_RETENTION_DAYS`, `USER_RETENTION_DAYS`) | you (cookie or account) |
| Searches, collected postings, analyses | server database | same as above (postings are public job ads and are kept to power caching and market stats) | anyone with an analysis link (random 128-bit id) |
| Tracker, watches, digests | server database | until you delete them | you |
| Email address (if you sign in) | server database | until you delete your data | you; used only for sign-in links and digests you enable |
| AI keys | **your browser only** (session storage by default) | until the tab closes (or "remember" in local storage) | sent only with AI requests, never stored or logged by the server |
| AI usage log (tokens, cost; no content) | server database | with your other data | you (cost shown in reports) |
| Extension tokens | server database, hashed | until revoked | — |

- **AI processing.** Your resume and postings go to your chosen AI provider (OpenAI or Anthropic) only when you use an AI
  feature. Check your provider's retention settings (both offer zero/limited-retention options for API traffic).
- **Export / delete.** Settings → *Export my data* (JSON) and *Delete my data* (removes resumes, analyses, searches,
  tracker, watches, extension tokens and, when signed in, the account).
- **No tracking.** No analytics or third-party scripts; a strict Content-Security-Policy blocks them.
- **Logs** never contain resume text or keys (known key formats are masked in JSON logs).

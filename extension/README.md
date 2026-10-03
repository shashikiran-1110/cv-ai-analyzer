# CV Match Analyzer – browser extension (Manifest V3)

Scores the job posting **you are viewing** against your latest resume in your own CV Match Analyzer server, and can
save it to your tracker. It reads the page only when you click the toolbar button (`activeTab`), prefers the page's
schema.org `JobPosting` data, falls back to your text selection or the main page text, and sends only that posting
to your server. Nothing is scraped server-side; this is how sites that block bots (LinkedIn, Indeed, Wellfound) work.

1. In the app: **Settings → Browser extension → Create extension token** (shown once).
2. Chrome/Edge: `chrome://extensions` → Developer mode → **Load unpacked** → pick this `extension/` folder.
   Firefox: `about:debugging` → Load Temporary Add-on → `manifest.json`.
3. Open the extension's **Settings**, enter the server URL (default `http://localhost:8000`) and the token.
4. On a job page, click the toolbar icon → **Score**.

Revoke tokens any time in the app (Settings → Revoke all).

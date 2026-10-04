import { Sparkles } from "lucide-react";
import { useState } from "react";
import { useAi } from "../ai";
import { api, post } from "../api";
import { Markdown } from "../components/Markdown";
import { Alert, Meter } from "../components/ui";
import type { MarketStats } from "../types";

/** Market Analyst (ROADMAP §8.3 #12): numbers from postings collected so far; optional AI summary (numbers checked). */
export function MarketPage() {
  const ai = useAi();
  const [title, setTitle] = useState("");
  const [location, setLocation] = useState("");
  const [days, setDays] = useState(30);
  const [s, setS] = useState<MarketStats | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [story, setStory] = useState<{ text: string; numbers_unverified: string[] } | null>(null);

  async function load() {
    setBusy(true); setErr(""); setStory(null);
    try { setS(await api<MarketStats>(`/api/market?${new URLSearchParams({ title, location, days: String(days) })}`)); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  async function narrate() {
    if (!ai.usable) return ai.openModal(true);
    setBusy(true);
    try { setStory(await post("/api/market/narrate", { title, location, days }, ai.headers)); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  const maxWeek = Math.max(1, ...(s?.weekly_new ?? []).map((w) => w.jobs));
  return (
    <section className="enter" aria-labelledby="h-market">
      <h1 id="h-market">Market insights</h1>
      <p className="lead">What employers ask for in the postings this app has collected for a role. Run searches to build up data.</p>
      <form className="card market-form" onSubmit={(e) => { e.preventDefault(); void load(); }}>
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Role, e.g. Data Engineer" aria-label="Role" required minLength={2} />
        <input value={location} onChange={(e) => setLocation(e.target.value)} placeholder="Location (optional)" aria-label="Location" />
        <select value={days} onChange={(e) => setDays(+e.target.value)} aria-label="Period"><option value={7}>7 days</option><option value={30}>30 days</option><option value={90}>90 days</option></select>
        <button className="btn primary" disabled={busy || title.trim().length < 2}>{busy ? "Loading…" : "Analyse"}</button>
      </form>
      {err && <Alert>{err}</Alert>}
      {s && s.jobs === 0 && <Alert kind="info">{s.note}</Alert>}
      {s && s.jobs > 0 && <>
        <div className="stats-row" data-testid="market">
          <div className="card stat"><b>{s.jobs}</b><small>postings</small></div>
          <div className="card stat"><b>{s.remote_pct}%</b><small>remote</small></div>
          <div className="card stat"><b>{s.median_years_asked ?? "–"}</b><small>median years asked</small></div>
          <div className="card stat"><b>{s.top_companies?.length ?? 0}</b><small>top employers listed</small></div>
        </div>
        <div className="cols">
          <div className="card"><h2>Most-requested skills</h2>
            {s.top_skills?.map((k) => <div className="comp" key={k.skill}><span>{k.skill}</span><Meter value={k.pct} /><span>{k.pct}%</span></div>)}</div>
          <div className="card"><h2>New postings per week</h2>
            <div className="weeks">{s.weekly_new?.map((w) => <div key={w.week} title={`${w.week}: ${w.jobs}`}><i style={{ height: `${Math.round((w.jobs / maxWeek) * 80) + 4}px` }} /><small>{w.week.slice(5)}</small></div>)}</div>
            <h2>Top employers</h2><ul className="bullets">{s.top_companies?.slice(0, 6).map((c) => <li key={c.company}>{c.company} · {c.jobs}</li>)}</ul>
            {(s.salary?.length ?? 0) > 0 && <><h2>Salary (as posted)</h2>{s.salary!.map((x) => <p key={x.currency}>{x.currency}{x.p25.toLocaleString()}–{x.currency}{x.p75.toLocaleString()} (median {x.currency}{x.median_yearly.toLocaleString()}, {x.postings} postings)</p>)}<small className="muted">{s.salary_note}</small></>}
          </div>
        </div>
        <div className="card"><div className="head-row"><h2>AI summary</h2><button className="btn small" onClick={narrate} disabled={busy}><Sparkles aria-hidden="true" />Summarise</button></div>
          {story ? <><Markdown text={story.text} />{story.numbers_unverified.length > 0 && <small className="warn-text">Numbers not in the data: {story.numbers_unverified.join(", ")}</small>}</>
            : <p className="muted">The AI may only restate the numbers above; any number it adds is flagged.</p>}</div>
      </>}
    </section>
  );
}

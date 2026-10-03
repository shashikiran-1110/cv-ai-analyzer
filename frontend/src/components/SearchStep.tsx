import { useEffect, useState } from "react";
import { api, post } from "../api";
import { useAi } from "../ai";
import type { JobSummary, SearchParams, SearchStatus } from "../types";
import { Alert } from "./ui";

const TIME = [["24h", "24 hours"], ["week", "Week"], ["month", "Month"], ["any", "Any"], ["custom", "Custom"]] as const;
const EXPERIENCE = [["internship", "Internship"], ["entry", "Entry"], ["associate", "Associate"], ["mid_senior", "Mid-Senior"], ["director", "Director"], ["executive", "Executive"]];
const TYPES = [["full_time", "Full-time"], ["part_time", "Part-time"], ["contract", "Contract"], ["temporary", "Temporary"], ["internship", "Internship"]];
const WORKPLACE = [["on_site", "On-site"], ["hybrid", "Hybrid"], ["remote", "Remote"]];
const RECENT_KEY = "cvm.recent";

const DEFAULTS: SearchParams = { title: "", location: "", count: 25, time_range: "week", experience: [], job_types: [], workplace: [], sort: "recent" };

function loadRecent(): SearchParams[] {
  try { return JSON.parse(localStorage.getItem(RECENT_KEY) || "[]"); } catch { return []; }
}

function MultiChips({ label, options, value, onChange }: { label: string; options: string[][]; value: string[]; onChange: (v: string[]) => void }) {
  return (
    <div className="field">
      <span>{label} <small>(optional, pick any)</small></span>
      <div className="toggles" role="group" aria-label={label}>
        {options.map(([v, l]) => (
          <button key={v} type="button" className={`toggle ${value.includes(v) ? "on" : ""}`} aria-pressed={value.includes(v)}
            onClick={() => onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v])}>{l}</button>
        ))}
      </div>
    </div>
  );
}

export function SearchStep({ initial, onDone }: { initial: SearchParams | null; onDone: (searchId: string, jobs: JobSummary[], q: SearchStatus["query"]) => void }) {
  const ai = useAi();
  const [p, setP] = useState<SearchParams>(initial ?? DEFAULTS);
  const [hours, setHours] = useState(72);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [prog, setProg] = useState({ text: "", pct: 0 });
  const [recent, setRecent] = useState<SearchParams[]>(loadRecent);
  const max = ai.config?.max_jobs ?? 100;
  const upd = (patch: Partial<SearchParams>) => setP((x) => ({ ...x, ...patch }));

  useEffect(() => { if (initial) setP(initial); }, [initial]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    const title = p.title.trim();
    if (title.length < 2) return setErr("Enter a job title (at least 2 characters).");
    const count = Math.round(p.count);
    if (!(count >= 1 && count <= max)) return setErr(`Number of posts must be between 1 and ${max}.`);
    if (p.time_range === "custom" && !(hours >= 1 && hours <= 2160)) return setErr("Custom hours must be between 1 and 2160.");
    const body: SearchParams = { ...p, title, location: p.location.trim(), count, ...(p.time_range === "custom" ? { custom_hours: Math.round(hours) } : {}) };
    setBusy(true); setProg({ text: "Starting search…", pct: 0 });
    try {
      const { search_id } = await post<{ search_id: string }>("/api/search", body);
      let misses = 0;
      for (;;) {
        await new Promise((r) => setTimeout(r, 900));
        let s: SearchStatus;
        try { s = await api<SearchStatus>(`/api/search/${search_id}`); misses = 0; }
        catch (e) { if (++misses >= 5) throw e; continue; }
        if (s.status === "error") throw new Error(s.error || "Search failed.");
        if (s.status === "done") {
          if (!s.jobs?.length) throw new Error("LinkedIn returned no jobs for that search. Try a broader title or location, fewer filters, or a longer time range.");
          const next = [body, ...recent.filter((r) => r.title !== body.title || r.location !== body.location)].slice(0, 6);
          setRecent(next);
          try { localStorage.setItem(RECENT_KEY, JSON.stringify(next)); } catch { /* ignore */ }
          onDone(search_id, s.jobs, s.query);
          return;
        }
        const total = Math.max(1, s.total);
        setProg(s.stage === "details"
          ? { text: `Reading job descriptions (${s.done}/${total})…`, pct: 30 + Math.round((s.done / total) * 70) }
          : { text: `Searching LinkedIn… found ${s.done} of ${total}`, pct: Math.round((s.done / total) * 30) });
      }
    } catch (ex) { setErr((ex as Error).message); }
    finally { setBusy(false); }
  }

  return (
    <section aria-labelledby="h-search">
      <h1 id="h-search">Find real openings, then see how you stack up</h1>
      <p className="lead">Pull live postings from LinkedIn's public job search, then upload your resume to see how many you'd qualify for and what to work on.</p>
      {recent.length > 0 && (
        <div className="recent"><small>Recent:</small>
          {recent.map((r, i) => <button key={i} className="chip clickable" type="button" onClick={() => setP({ ...DEFAULTS, ...r })}>{r.title}{r.location ? ` · ${r.location}` : ""}</button>)}
          <button className="link" type="button" onClick={() => { setRecent([]); try { localStorage.removeItem(RECENT_KEY); } catch { /* ignore */ } }}>clear</button>
        </div>
      )}
      <form className="card form-grid" onSubmit={submit} noValidate>
        <label className="field span2"><span>Job title <b className="req">*</b></span>
          <input value={p.title} onChange={(e) => upd({ title: e.target.value })} maxLength={100} placeholder="e.g. Data Engineer" autoComplete="off" autoFocus />
        </label>
        <label className="field span2"><span>Location</span>
          <input value={p.location} onChange={(e) => upd({ location: e.target.value })} maxLength={100} placeholder="e.g. London, or Remote (blank = anywhere)" autoComplete="off" />
        </label>
        <div className="field"><span>Number of posts</span>
          <div className="count-row">
            <input type="range" min={5} max={max} step={5} value={Math.max(5, Math.min(max, p.count || 5))} aria-label="Number of posts slider" onChange={(e) => upd({ count: +e.target.value })} />
            <input type="number" min={1} max={max} value={p.count || ""} aria-label="Number of posts" onChange={(e) => upd({ count: +e.target.value })} />
          </div>
          <small>1–{max}. About 1 second per post.</small>
        </div>
        <div className="field"><span>Posted within</span>
          <div className="seg" role="radiogroup" aria-label="Time range">
            {TIME.map(([v, l]) => <button key={v} type="button" role="radio" aria-checked={p.time_range === v} onClick={() => upd({ time_range: v })}>{l}</button>)}
          </div>
          {p.time_range === "custom" && <div className="custom-row"><input type="number" min={1} max={2160} value={hours} onChange={(e) => setHours(+e.target.value)} aria-label="Custom hours" /> <span>hours</span></div>}
        </div>
        <MultiChips label="Experience level" options={EXPERIENCE} value={p.experience} onChange={(v) => upd({ experience: v })} />
        <MultiChips label="Job type" options={TYPES} value={p.job_types} onChange={(v) => upd({ job_types: v })} />
        <MultiChips label="Workplace" options={WORKPLACE} value={p.workplace} onChange={(v) => upd({ workplace: v })} />
        <div className="field"><span>Sort by</span>
          <div className="seg" role="radiogroup" aria-label="Sort">
            {[["recent", "Most recent"], ["relevant", "Most relevant"]].map(([v, l]) => <button key={v} type="button" role="radio" aria-checked={p.sort === v} onClick={() => upd({ sort: v })}>{l}</button>)}
          </div>
        </div>
        <div className="span2 actions"><button className="btn primary" disabled={busy}>{busy ? "Fetching…" : "Fetch jobs from LinkedIn"}</button></div>
      </form>

      {busy && (
        <div className="card progress" aria-live="polite">
          <div className="p-top"><span>{prog.text}</span><span>{prog.pct}%</span></div>
          <div className="bar"><i style={{ width: `${prog.pct}%` }} /></div>
          <small>Reading public LinkedIn listings. No login is used, and your resume is not sent there.</small>
        </div>
      )}
      {err && <Alert>{err}</Alert>}
      <p className="fine">Data comes from LinkedIn's public guest job pages. LinkedIn may throttle or change them at any time; if a search fails, wait a few minutes or ask for fewer posts. Check LinkedIn's terms before heavy use.</p>
    </section>
  );
}

import { useMemo, useState } from "react";
import type { SearchStatus } from "../types";
import { SourceBadges, sourceName } from "./SourceBadge";
import { Alert, safeUrl } from "./ui";

export function JobsStep({ search, searchId, onBack, analyze }: {
  search: SearchStatus; searchId: string; onBack: () => void;
  analyze: (searchId: string, ids: string[], onStage: (s: string) => void, notes?: string[]) => Promise<void>;
}) {
  const jobs = search.jobs ?? [];
  const [selected, setSelected] = useState<Set<string>>(() => new Set(jobs.map((j) => j.id)));
  const [filter, setFilter] = useState("");
  const [exclude, setExclude] = useState("");
  const [src, setSrc] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const q = search.query;
  const bySource = useMemo(() => { const m: Record<string, number> = {}; jobs.forEach((j) => (m[j.source] = (m[j.source] ?? 0) + 1)); return m; }, [jobs]);

  const visible = useMemo(() => {
    const f = filter.trim().toLowerCase();
    const ex = exclude.split(",").map((x) => x.trim().toLowerCase()).filter(Boolean);
    return jobs.filter((j) => (!f || `${j.title} ${j.company} ${j.location}`.toLowerCase().includes(f))
      && !ex.some((x) => j.title.toLowerCase().includes(x)) && (!src || j.sources.includes(src)));
  }, [jobs, filter, exclude, src]);
  const visSel = visible.filter((j) => selected.has(j.id)).length;
  const toggle = (id: string) => { const n = new Set(selected); n.has(id) ? n.delete(id) : n.add(id); setSelected(n); };
  const setVisible = (on: boolean) => { const n = new Set(selected); visible.forEach((j) => (on ? n.add(j.id) : n.delete(j.id))); setSelected(n); };

  async function go() {
    setBusy(true); setErr("");
    const notes = [...(search.warnings ?? []), ...(search.sources ?? []).filter((x) => x.status === "error").map((x) => `${x.name}: ${x.message}`)];
    try { await analyze(searchId, [...selected], () => {}, notes); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <section aria-labelledby="h-jobs">
      <div className="head-row">
        <div><h1 id="h-jobs">Review jobs</h1>
          <p className="lead">{jobs.length} postings for “{q.title}”{q.location ? ` in ${q.location}` : ""} · {Object.entries(bySource).map(([k, v]) => `${sourceName(k)} ${v}`).join(" · ")}</p></div>
        <div className="actions">
          <button className="btn" onClick={onBack}>← Back to setup</button>
          <button className="btn primary" disabled={!selected.size || busy} onClick={go}>{busy ? "Analyzing…" : `Analyze ${selected.size} jobs →`}</button>
        </div>
      </div>
      {(search.warnings ?? []).map((w, i) => <Alert key={i} kind="warn">{w}</Alert>)}
      {(search.sources ?? []).filter((s) => s.status === "error").map((s) => <Alert key={s.id} kind="info"><b>{s.name}:</b> {s.message}</Alert>)}
      {err && <Alert>{err}</Alert>}
      <div className="card">
        <div className="toolbar">
          <label className="check"><input type="checkbox" checked={visible.length > 0 && visSel === visible.length}
            ref={(el) => { if (el) el.indeterminate = visSel > 0 && visSel < visible.length; }} onChange={(e) => setVisible(e.target.checked)} /> Select shown</label>
          <input type="search" placeholder="Filter…" aria-label="Filter jobs" value={filter} onChange={(e) => setFilter(e.target.value)} />
          <input type="text" placeholder="Hide titles containing… (comma-separated)" aria-label="Hide titles containing" value={exclude} onChange={(e) => setExclude(e.target.value)} />
          <select value={src} onChange={(e) => setSrc(e.target.value)} aria-label="Source filter">
            <option value="">All sources</option>{Object.keys(bySource).map((k) => <option key={k} value={k}>{sourceName(k)}</option>)}
          </select>
        </div>
        <ul className="joblist">
          {visible.length === 0 && <li className="empty">No jobs match those filters.</li>}
          {visible.map((j) => (
            <li key={j.id}>
              <input type="checkbox" aria-label={`Include ${j.title} at ${j.company}`} checked={selected.has(j.id)} onChange={() => toggle(j.id)} />
              <div className="job-main">
                <div className="job-title">{j.url ? <a href={safeUrl(j.url)} target="_blank" rel="noopener noreferrer">{j.title}</a> : j.title}
                  {j.description_missing && <span className="pill" title="No description could be loaded; the match will be a rough estimate">no description</span>}</div>
                <div className="job-sub">{[j.company, j.location, j.salary, j.employment_type, j.posted?.slice(0, 10)].filter(Boolean).join(" · ")}</div>
                <div className="badges"><SourceBadges sources={j.sources} /></div>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

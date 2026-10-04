import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ExternalLink, Funnel, PenLine, Search } from "lucide-react";
import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import type { Analysis, ScoredJob, SearchStatus } from "../types";
import { HBars } from "./charts";
import { dropText } from "./SearchProgress";
import { SourceBadges, sourceName } from "./SourceBadge";
import { qualifies, relTime } from "./table/JobsTable";
import { safeUrl } from "./ui";

const median = (xs: number[]) => { if (!xs.length) return 0; const s = [...xs].sort((a, b) => a - b); const m = s.length >> 1; return s.length % 2 ? s[m] : Math.round((s[m - 1] + s[m]) / 2); };
const top = (m: Map<string, { n: number; q: number }>, k = 8) => [...m.entries()].sort((a, b) => b[1].n - a[1].n || b[1].q - a[1].q).slice(0, k);
const city = (loc: string) => (loc || "Unspecified").split(/[,(;|]/)[0].trim() || "Unspecified";

function count(jobs: ScoredJob[], key: (j: ScoredJob) => string, t: number) {
  const m = new Map<string, { n: number; q: number }>();
  for (const j of jobs) {
    const k = key(j);
    const v = m.get(k) ?? { n: 0, q: 0 };
    v.n++; if (qualifies(j, t)) v.q++;
    m.set(k, v);
  }
  return m;
}

/** "What's in this search" — KPIs, where you qualify (links open the posting on its portal), near misses,
 *  breakdowns that filter the table when clicked, and the fetch funnel (why postings were dropped). */
export function JobsAnalytics({ a, threshold, onOpen }: { a: Analysis; threshold: number; onOpen: (j: ScoredJob) => void }) {
  const [params, setParams] = useSearchParams();
  const open = params.get("an") !== "0";
  const setParam = (k: string, v: string | null) => setParams((p) => { const n = new URLSearchParams(p); if (!v) n.delete(k); else n.set(k, v); return n; }, { replace: true });
  const search = useQuery({ queryKey: ["search", a.search_id], queryFn: () => api<SearchStatus>(`/api/search/${a.search_id}`), enabled: !!a.search_id && open, staleTime: Infinity, retry: 0 });

  const s = useMemo(() => {
    const jobs = a.jobs, t = threshold;
    const q = jobs.filter((j) => qualifies(j, t)).sort((x, y) => y.score - x.score);
    const near = jobs.filter((j) => !qualifies(j, t) && (j.score >= t || j.score >= t - 15)).sort((x, y) => y.score - x.score);
    const remote = jobs.filter((j) => j.remote === true || /remote/i.test(j.location)).length;
    const salaried = jobs.filter((j) => j.salary).length;
    const ages = jobs.map((j) => (Date.parse(j.posted) ? (Date.now() - Date.parse(j.posted)) / 864e5 : null));
    const recency = [["≤ 1 day", 1], ["≤ 1 week", 7], ["≤ 1 month", 31], ["older", Infinity]].map(([l, d], i, arr) => {
      const lo = i ? (arr[i - 1][1] as number) : -1;
      return { label: l as string, value: ages.filter((x) => x !== null && x > lo && x <= (d as number)).length };
    });
    const unknownAge = ages.filter((x) => x === null).length;
    if (unknownAge) recency.push({ label: "date unknown", value: unknownAge });
    return {
      q, near, remote, salaried, recency, median: median(jobs.map((j) => j.score)),
      companies: top(count(jobs, (j) => j.company || "Unknown", t)), sources: top(count(jobs, (j) => j.source, t), 12),
      locations: top(count(jobs, (j) => (j.remote === true && !j.location ? "Remote" : city(j.location)), t)),
      work: [...count(jobs, (j) => (j.remote === true || /remote/i.test(j.location) ? "Remote" : j.remote === false ? "On-site / hybrid" : "Not stated"), t).entries()],
    };
  }, [a.jobs, threshold]);

  const n = a.jobs.length;
  const f = search.data?.funnel ?? {};
  const dropped = (search.data?.sources ?? []).reduce<Record<string, number>>((acc, src) => { for (const [k, v] of Object.entries(src.dropped ?? {})) acc[k] = (acc[k] ?? 0) + v; return acc; }, {});
  const blocker = (j: ScoredJob) => j.gates_failed?.[0] ? `Hard requirement: ${j.gates_failed[0]}` : j.required_missing[0] ? `Missing ${j.required_missing.slice(0, 2).join(", ")}` : `${threshold - j.score} points below your bar`;

  return (
    <section className="analytics" aria-label="Jobs analytics">
      <button type="button" className="disclosure an-toggle" aria-expanded={open} onClick={() => setParam("an", open ? "0" : null)}>
        <ChevronDown aria-hidden="true" style={{ transform: open ? "none" : "rotate(-90deg)" }} />Analytics for these {n} jobs</button>
      {open && <>
        <div className="kpis">
          <div className="kpi"><span className="k-label">Qualified at {threshold}%+</span><b>{s.q.length}<small> / {n}</small></b><div className="k-sub">{n ? Math.round((s.q.length / n) * 100) : 0}% · no failed hard requirement</div></div>
          <div className="kpi"><span className="k-label">Near misses</span><b>{s.near.length}</b><div className="k-sub">within 15 points, or blocked by one requirement</div></div>
          <div className="kpi"><span className="k-label">Median match</span><b>{s.median}<small>%</small></b><div className="k-sub">{s.remote} remote · {s.salaried} with salary</div></div>
          {f.fetched ? (
            <div className="kpi"><span className="k-label">Fetched → used</span><b>{f.fetched}<small> → {f.selected ?? n}</small></b>
              <div className="k-sub" title={dropText(dropped, 6)}>{dropText(dropped, 2) ? `dropped: ${dropText(dropped, 2)}` : "postings collected from all sources"}</div></div>
          ) : (
            <div className="kpi"><span className="k-label">Jobs in this report</span><b>{n}</b><div className="k-sub">pasted or sample postings (nothing fetched)</div></div>
          )}
        </div>

        <div className="an-grid">
          <div className="card where" data-testid="where-qualify">
            <div className="card-head"><div><h2>Where you qualify</h2><small>Click a title to open the posting on its job portal.</small></div></div>
            {s.q.length === 0 ? <p className="muted">No job clears {threshold}% without a failed hard requirement yet. Your near misses are below; the Skills tab shows what would unlock them.</p> : (
              <ul className="q-list">
                {s.q.slice(0, 25).map((j) => (
                  <li key={j.id}>
                    <span className={`score small ${j.score >= threshold ? "hi" : "mid"}`}>{j.score}%</span>
                    <div className="q-main">
                      {j.url ? <a className="q-title" href={safeUrl(j.url)} target="_blank" rel="noopener noreferrer" title={`Open on ${sourceName(j.source)}`}>{j.title}<ExternalLink aria-hidden="true" /></a>
                        : <span className="q-title">{j.title}</span>}
                      <span className="t-sub">{[j.company, j.location, j.salary, relTime(j.posted)].filter(Boolean).join(" · ")} <SourceBadges sources={j.sources} /></span>
                    </div>
                    <div className="q-actions">
                      <button className="btn small ghost" onClick={() => onOpen(j)}>Details</button>
                      <Link className="btn small ghost" to={`/analysis/${a.analysis_id}/tailor/${j.id}`} title="Tailor your resume for this job"><PenLine aria-hidden="true" /></Link>
                    </div>
                  </li>))}
                {s.q.length > 25 && <li className="muted"><button className="link" onClick={() => setParam("st", "qualified")}>Show all {s.q.length} in the table</button></li>}
              </ul>)}
            {s.near.length > 0 && <>
              <h3 className="sec">Near misses <small className="muted">(what's blocking each)</small></h3>
              <ul className="q-list near">
                {s.near.slice(0, 8).map((j) => (
                  <li key={j.id}>
                    <span className="score small mid">{j.score}%</span>
                    <div className="q-main">
                      {j.url ? <a className="q-title" href={safeUrl(j.url)} target="_blank" rel="noopener noreferrer">{j.title}<ExternalLink aria-hidden="true" /></a> : <span className="q-title">{j.title}</span>}
                      <span className="t-sub">{j.company} · <span className="warn-text">{blocker(j)}</span></span>
                    </div>
                    <div className="q-actions"><button className="btn small ghost" onClick={() => onOpen(j)}>Details</button></div>
                  </li>))}
              </ul></>}
          </div>

          <div className="an-side">
            <div className="card"><h2>By source <small className="muted">all / qualified</small></h2>
              <HBars show="count" total={n} rows={s.sources.map(([k, v]) => ({ label: sourceName(k), value: v.n, sub: v.q, hint: `${v.q} of ${v.n} qualify · click to filter` }))}
                onPick={(label) => { const id = s.sources.find(([k]) => sourceName(k) === label)?.[0]; if (id) setParam("src", id); }} />
            </div>
            {(f.fetched ?? 0) > 0 && (
              <div className="card funnel"><h2><Funnel aria-hidden="true" />How these jobs were chosen</h2>
                <ol>
                  <li><b>{f.fetched}</b> fetched from {(search.data?.sources ?? []).length} sources</li>
                  <li><b>{f.relevant}</b> had a matching job title</li>
                  <li><b>{f.after_filters}</b> passed location, date and other filters</li>
                  <li><b>{f.unique}</b> after removing duplicates</li>
                  <li><b>{f.selected}</b> kept for scoring{f.enriched ? ` (${f.enriched} filled in from their own pages)` : ""}</li>
                </ol>
                {dropText(dropped, 6) && <small className="muted">Dropped: {dropText(dropped, 6)}.</small>}
              </div>)}
          </div>
        </div>

        <div className="cols three an-charts">
          <div className="card"><h2>Top companies <small className="muted">jobs / qualified</small></h2>
            <HBars show="count" total={n} rows={s.companies.map(([k, v]) => ({ label: k, value: v.n, sub: v.q }))} onPick={(c) => setParam("q", c)} /></div>
          <div className="card"><h2>Top locations</h2>
            <HBars show="count" total={n} rows={s.locations.map(([k, v]) => ({ label: k, value: v.n, sub: v.q }))} onPick={(c) => setParam("q", c === "Unspecified" ? null : c)} /></div>
          <div className="card"><h2>Freshness & workplace</h2>
            <HBars show="count" total={n} rows={s.recency.filter((r) => r.value)} />
            <div style={{ height: 10 }} />
            <HBars show="count" total={n} rows={s.work.map(([k, v]) => ({ label: k, value: v.n, sub: v.q }))} /></div>
        </div>
        {params.get("q") && <div className="filter-note"><Search size={13} aria-hidden="true" /> Table filtered to “{params.get("q")}”. <button className="link" onClick={() => setParam("q", null)}>Clear</button></div>}
      </>}
    </section>
  );
}

import { CalendarCheck, Compass, ExternalLink, PenLine, RotateCcw, ShieldCheck, Target } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useAi } from "../ai";
import { post } from "../api";
import type { Analysis, Strategy } from "../types";
import { Feedback } from "./Feedback";
import { IconWarn } from "./Icons";
import { useToast } from "./Toast";
import { Alert, safeUrl } from "./ui";

const PRIORITY: Record<number, [string, string]> = { 1: ["Apply now", "p1"], 2: ["Apply after tailoring", "p2"], 3: ["Stretch", "p3"] };

/** AI apply strategy: a prioritised shortlist grounded in the scores (ids, gates and numbers checked server-side). */
export function StrategyCard({ a, threshold }: { a: Analysis; threshold: number }) {
  const ai = useAi();
  const toast = useToast();
  const [st, setSt] = useState<Strategy | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const s = st ?? a.strategy;
  if (!s) return null;
  const byId = new Map(a.jobs.map((j) => [j.id, j]));
  async function rebuild() {
    if (!ai.usable) return ai.openModal(true);
    setBusy(true);
    try { setSt(await post<Strategy>(`/api/analysis/${a.analysis_id}/strategy`, {}, ai.headers)); toast("Apply strategy rebuilt.", "ok"); }
    catch (e) { toast((e as Error).message, "error"); } finally { setBusy(false); }
  }
  if (s.pending) return <div className="card shimmer" aria-live="polite"><b>Building your apply strategy…</b> <small className="muted">Which jobs to apply to first, and what to tailor for each.</small></div>;
  if (s.error) return <Alert kind="warn">{s.error} <button className="link" onClick={rebuild} disabled={busy}>Try again</button></Alert>;
  const groups = [1, 2, 3].map((p) => [p, (s.shortlist ?? []).filter((x) => x.priority === p)] as const).filter(([, xs]) => xs.length);
  return (
    <div className="card strategy" data-testid="strategy">
      <div className="card-head">
        <Target aria-hidden="true" className="head-icon" />
        <div><h2>Apply strategy</h2><small>AI-ranked from your scores at a {threshold}% bar{s.model ? ` · ${s.model}` : ""}. Every job id and hard requirement is checked by the server.</small></div>
        <div className="actions">
          <Feedback target={{ kind: "strategy", analysisId: a.analysis_id, output: JSON.stringify({ shortlist: s.shortlist, skip: s.skip }) }} label="this strategy" />
          <button className="btn small ghost" onClick={rebuild} disabled={busy}><RotateCcw aria-hidden="true" />{busy ? "Rebuilding…" : "Rebuild"}</button>
        </div>
      </div>
      {(s.themes?.length ?? 0) > 0 && <div className="chips">{s.themes!.map((t) => <span key={t} className="chip">{t}</span>)}</div>}
      {groups.length === 0 && <p className="muted">The AI didn't shortlist any job from this search.</p>}
      {groups.map(([p, xs]) => (
        <div key={p} className={`prio ${PRIORITY[p][1]}`}>
          <h3 className="sec"><span className={`prio-dot ${PRIORITY[p][1]}`} />{PRIORITY[p][0]} <small className="muted">({xs.length})</small></h3>
          <ul className="pick-list">
            {xs.map((x) => {
              const j = byId.get(x.job_id);
              return (
                <li key={x.job_id}>
                  <div className="pick-head">
                    <span className={`score small ${x.score >= threshold ? "hi" : x.score >= threshold - 15 ? "mid" : "lo"}`}>{x.score}%</span>
                    {j?.url ? <a className="q-title" href={safeUrl(j.url)} target="_blank" rel="noopener noreferrer">{x.title}<ExternalLink aria-hidden="true" /></a> : <b>{x.title}</b>}
                    <span className="muted small">{x.company}</span>
                    <span className="pick-actions">
                      <Link className="btn small ghost" to={`/analysis/${a.analysis_id}/job/${x.job_id}`}>Details</Link>
                      <Link className="btn small ghost" to={`/analysis/${a.analysis_id}/tailor/${x.job_id}`}><PenLine aria-hidden="true" />Tailor</Link>
                    </span>
                  </div>
                  <p>{x.why}</p>
                  {x.tailor_points.length > 0 && <ul className="bullets small">{x.tailor_points.map((t) => <li key={t}>{t}</li>)}</ul>}
                  {x.risk && <div className="small warn-text"><IconWarn /> {x.risk}</div>}
                  {x.demoted && <div className="small muted">Moved down from “apply now”: it fails a hard requirement ({x.gates_failed.join(", ")}) the AI didn't mention.</div>}
                </li>);
            })}
          </ul>
        </div>
      ))}
      {(s.next_steps?.length ?? 0) > 0 && <><h3 className="sec">This week</h3><ol className="steps-list">{s.next_steps!.map((n) => <li key={n}>{n}</li>)}</ol></>}
      {(s.skip?.length ?? 0) > 0 && (
        <details className="skip"><summary>Skip for now ({s.skip!.length})</summary>
          <ul className="bullets small">{s.skip!.map((x) => <li key={x.job_id}><b>{x.title}</b> <span className="muted">{x.company} · {x.score}%</span> — {x.reason}</li>)}</ul>
        </details>)}
      {(s.dropped_ids?.length ?? 0) > 0 && <small className="muted">The AI suggested {s.dropped_ids!.length} job{s.dropped_ids!.length > 1 ? "s" : ""} that aren't in this report; removed.</small>}
      {(s.unverified_numbers?.length ?? 0) > 0 && <div className="small warn-text"><IconWarn /> Numbers not found in your analysis: {s.unverified_numbers!.join(", ")}. Treat them with caution.</div>}
    </div>
  );
}

/** Deeper AI narrative: market fit, strongest areas, adjacent roles and a 4-week gap plan. */
export function CareerReport({ a }: { a: Analysis }) {
  const ins = a.insights;
  if (!ins.market_fit && !(ins.career_paths?.length) && !(ins.gap_plan?.length)) return null;
  return (
    <div className="card career" data-testid="career-report">
      <div className="card-head"><Compass aria-hidden="true" className="head-icon" /><div><h2>AI career report</h2><small>How your profile fits this market, and where to go next.</small></div>
        <div className="actions"><Feedback target={{ kind: "insights", analysisId: a.analysis_id, itemId: "career_report", output: JSON.stringify({ market_fit: ins.market_fit, career_paths: ins.career_paths, gap_plan: ins.gap_plan }) }} label="this report" /></div></div>
      {ins.market_fit && <p className="lead-p">{ins.market_fit}</p>}
      {(ins.strongest_areas?.length ?? 0) > 0 && <div className="chips">{ins.strongest_areas!.map((x) => <span key={x} className="chip ok">{x}</span>)}</div>}
      <div className="cols" style={{ marginTop: 8 }}>
        {(ins.career_paths?.length ?? 0) > 0 && (
          <div><h3 className="sec">Roles you could target</h3>
            <ul className="paths">{ins.career_paths!.map((p) => <li key={p.title}><b>{p.title}</b><span>{p.why}</span><small className="warn-text">Gap: {p.gap}</small></li>)}</ul></div>)}
        {(ins.gap_plan?.length ?? 0) > 0 && (
          <div><h3 className="sec"><CalendarCheck aria-hidden="true" />4-week plan</h3>
            <ol className="weeks-plan">{ins.gap_plan!.map((w) => <li key={w.week}><span className="wk">Week {w.week}</span><b>{w.focus}</b><small>{w.outcome}</small></li>)}</ol></div>)}
      </div>
      {(ins.unsupported_strengths?.length ?? 0) > 0 && <div className="small warn-text"><IconWarn /> Some strengths mention things not on your resume: {ins.unsupported_strengths!.join(" ")}</div>}
    </div>
  );
}

export function AutoDeepBanner({ a }: { a: Analysis }) {
  const d = a.auto_deep;
  if (!d) return null;
  if (d.status === "skipped") return <Alert kind="info"><ShieldCheck size={14} /> Auto deep-check skipped: {d.reason}</Alert>;
  if (d.status === "done") return d.errors?.length ? <Alert kind="warn">Auto deep-check finished with {d.errors.length} error{d.errors.length > 1 ? "s" : ""}: {[...new Set(d.errors)].join(" | ")}</Alert> : null;
  const pct = d.total ? Math.round((d.done / d.total) * 100) : 0;
  return (
    <div className="card tight auto-deep" aria-live="polite" data-testid="auto-deep">
      <div className="p-top"><span><ShieldCheck size={14} aria-hidden="true" /> {d.status === "queued" ? `AI will verify your top ${d.total} jobs after the advice is written…` : `AI is verifying your top jobs: ${d.done}/${d.total}`}</span>
        {d.estimate_usd != null && <small className="muted">≈ ${d.estimate_usd.toFixed(2)}</small>}</div>
      <div className="bar"><i style={{ width: `${pct}%` }} /></div>
    </div>
  );
}

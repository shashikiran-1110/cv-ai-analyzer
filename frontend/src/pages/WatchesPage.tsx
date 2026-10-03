import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, post } from "../api";
import { Skeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { safeUrl } from "../components/ui";
import type { Digest, Watch } from "../types";

const when = (t: number | null) => (t ? new Date(t * 1000).toLocaleString() : "never");

/** Saved searches: re-run on a schedule, report only postings you haven't seen (ROADMAP §8.3 #11). */
export function WatchesPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["watches"], queryFn: () => api<{ items: Watch[]; email_available: boolean }>("/api/watches") });
  const [busy, setBusy] = useState<string | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["watches"] });

  async function patch(id: string, body: Partial<Watch>) {
    try { await api(`/api/watches/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); void refresh(); }
    catch (e) { toast((e as Error).message, "error"); }
  }
  async function runNow(id: string) {
    setBusy(id);
    try { const d = await post<Digest>(`/api/watches/${id}/run`, {}); toast(`${d.new} new posting(s), ${d.qualifying} you qualify for.`, "ok"); void refresh(); }
    catch (e) { toast((e as Error).message, "error"); } finally { setBusy(null); }
  }
  async function remove(id: string) {
    if (!confirm("Delete this watch and its digests?")) return;
    await api(`/api/watches/${id}`, { method: "DELETE" }); void refresh();
  }

  if (q.isPending) return <section className="enter"><h1>Watches</h1><Skeleton rows={4} /></section>;
  const items = q.data?.items ?? [];
  return (
    <section className="enter" aria-labelledby="h-watch">
      <div className="head-row"><div><h1 id="h-watch">Watches</h1>
        <p className="lead">Saved searches re-run {q.data?.email_available ? "and email you" : "in the background"} when new postings match your resume.</p></div></div>
      {!q.data?.email_available && <div className="alert info">Digests appear here. <Link to="/settings">Sign in</Link> to also get them by email.</div>}
      {!items.length && <div className="card empty-state"><p>No watches yet. In a report, choose <b>Watch this search</b>.</p></div>}
      {items.map((w) => (
        <div key={w.id} className={`card watch ${w.active ? "" : "paused"}`} data-testid="watch">
          <div className="watch-head">
            <div><h2>{w.query.title}{w.query.location ? ` · ${w.query.location}` : ""}</h2>
              <small className="muted">{w.query.sources.join(", ")} · last run {when(w.last_run_at)} · next {w.active ? when(w.next_run_at) : "paused"}</small></div>
            <div className="actions">
              <select value={w.frequency} aria-label="Frequency" onChange={(e) => patch(w.id, { frequency: e.target.value as Watch["frequency"] })}>
                <option value="daily">Daily</option><option value="weekly">Weekly</option></select>
              <label className="check small"><input type="checkbox" checked={w.email} disabled={!q.data?.email_available} onChange={(e) => patch(w.id, { email: e.target.checked })} /> Email</label>
              <button className="btn small" onClick={() => patch(w.id, { active: !w.active })}>{w.active ? "Pause" : "Resume"}</button>
              <button className="btn small primary" onClick={() => runNow(w.id)} disabled={busy === w.id}>{busy === w.id ? "Running…" : "Run now"}</button>
              <button className="btn small danger" onClick={() => remove(w.id)}>Delete</button>
            </div>
          </div>
          {w.latest ? <div className="digest">
            <p><b>{w.latest.new}</b> new of {w.latest.searched} found · <b>{w.latest.qualifying}</b> at ≥ {w.threshold}% with no failed hard requirement{w.latest.emailed ? " · emailed" : ""} · {when(w.latest.created_at)}</p>
            {w.latest.resume_missing && <small className="warn-text">The saved resume expired; open a new analysis and watch it again.</small>}
            <ul className="digest-list">{w.latest.matches.slice(0, 10).map((m) => (
              <li key={m.job_id}><span className={`score small ${m.qualifies ? "hi" : "lo"}`}>{m.score}%</span>
                <a href={safeUrl(m.url)} target="_blank" rel="noopener noreferrer">{m.title}</a> <span className="muted">· {m.company}{m.location ? ` · ${m.location}` : ""}</span>
                {m.gates_failed.map((g) => <span key={g} className="tag gate">✕ {g}</span>)}</li>))}</ul>
          </div> : <p className="muted">No digest yet. It runs {w.frequency}; use Run now to check immediately.</p>}
        </div>
      ))}
    </section>
  );
}

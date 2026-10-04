import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock, FileText, Plus, ShieldCheck, Trash } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Skeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import type { AnalysisListItem } from "../types";

const when = (t: number) => new Date(t * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

/** Report history for this browser (or account): reopen or delete past analyses. */
export function ReportsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["analyses"], queryFn: () => api<AnalysisListItem[]>("/api/analyses") });
  async function remove(id: string) {
    try {
      await api(`/api/analysis/${id}`, { method: "DELETE" });
      qc.setQueryData<AnalysisListItem[]>(["analyses"], (old) => (old ?? []).filter((x) => x.analysis_id !== id));
      qc.removeQueries({ queryKey: ["analysis", id] });
      toast("Report deleted.", "ok");
    } catch (e) { toast((e as Error).message, "error"); }
  }
  return (
    <section aria-labelledby="h-reports">
      <div className="page-head">
        <div><h1 id="h-reports">Reports</h1><p className="lead">Every analysis you've run in this browser{""} (or on your account when signed in). Anonymous reports are kept for 7 days.</p></div>
        <Link className="btn primary" to="/"><Plus aria-hidden="true" />New search</Link>
      </div>
      {q.isLoading && <Skeleton rows={5} />}
      {q.isError && <div className="alert error">{(q.error as Error).message}</div>}
      {q.data && q.data.length === 0 && (
        <div className="card empty-state"><Clock aria-hidden="true" /><h2>No reports yet</h2><p className="muted">Run a search to see how many openings you qualify for.</p><Link className="btn primary" to="/">Start a search</Link></div>
      )}
      {q.data && q.data.length > 0 && (
        <ul className="list">
          {q.data.map((r) => {
            const pct = r.job_count ? Math.round((r.qualifying / r.job_count) * 100) : 0;
            return (
              <li key={r.analysis_id}>
                <div style={{ minWidth: 0 }}>
                  <Link className="l-title" to={`/analysis/${r.analysis_id}`}><FileText size={14} aria-hidden="true" style={{ marginRight: 6, verticalAlign: -2, color: "var(--muted)" }} />{r.title || "Pasted / sample jobs"}{r.location ? ` · ${r.location}` : ""}</Link>
                  <div className="l-sub"><span>{when(r.created_at)}</span><span>{r.job_count} jobs</span>{r.best_title && <span>best: {r.best_title} ({r.best_score}%)</span>}
                    {r.verified > 0 && <span><ShieldCheck size={12} aria-hidden="true" style={{ verticalAlign: -2 }} /> {r.verified} AI-verified</span>}</div>
                </div>
                <div className="l-right">
                  <span className="num-t" title={`Qualified at ${r.threshold}%+`}><b>{r.qualifying}</b><span className="muted"> / {r.job_count} qualified · {pct}%</span></span>
                  <button className="icon-btn" aria-label={`Delete report ${r.title}`} title="Delete" onClick={() => remove(r.analysis_id)}><Trash /></button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

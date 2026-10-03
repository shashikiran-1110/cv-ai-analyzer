import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { Skeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { safeUrl } from "../components/ui";
import type { TrackerItem } from "../types";

const COLS: [string, string][] = [["saved", "Saved"], ["applied", "Applied"], ["interviewing", "Interviewing"], ["offer", "Offer"], ["rejected", "Rejected"]];

/** Application tracker (ROADMAP §9.6): drag cards between stages (or use the arrow buttons / keyboard). */
export function TrackerPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["tracker"], queryFn: () => api<{ items: TrackerItem[] }>("/api/tracker") });
  const [drag, setDrag] = useState<string | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const items = q.data?.items ?? [];

  async function patch(id: string, body: Partial<TrackerItem>) {
    const prev = q.data;
    qc.setQueryData<{ items: TrackerItem[] }>(["tracker"], (d) => d && { items: d.items.map((i) => (i.id === id ? { ...i, ...body } : i)) });
    try {
      const r = await api<TrackerItem>(`/api/tracker/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      qc.setQueryData<{ items: TrackerItem[] }>(["tracker"], (d) => d && { items: d.items.map((i) => (i.id === id ? r : i)) });
    } catch (e) { qc.setQueryData(["tracker"], prev); toast((e as Error).message, "error"); }
  }
  async function remove(id: string) {
    if (!confirm("Remove this application from the tracker?")) return;
    await api(`/api/tracker/${id}`, { method: "DELETE" });
    qc.setQueryData<{ items: TrackerItem[] }>(["tracker"], (d) => d && { items: d.items.filter((i) => i.id !== id) });
  }
  const move = (i: TrackerItem, dir: -1 | 1) => {
    const k = COLS.findIndex(([c]) => c === i.stage) + dir;
    if (k >= 0 && k < COLS.length) void patch(i.id, { stage: COLS[k][0] });
  };

  if (q.isPending) return <section className="enter"><h1>Applications</h1><Skeleton rows={5} /></section>;
  return (
    <section className="enter" aria-labelledby="h-tracker">
      <div className="head-row">
        <div><h1 id="h-tracker">Applications</h1><p className="lead">{items.length} tracked · drag cards between stages, or use ← →</p></div>
        <div className="actions"><a className="btn" href="/api/tracker.csv" download>Export CSV</a></div>
      </div>
      {!items.length && <div className="card empty-state"><p>Nothing tracked yet. Open a job in a report and choose <b>Save to tracker</b>, or use the browser extension on any job page.</p></div>}
      <div className="kanban" data-testid="kanban">
        {COLS.map(([stage, label]) => {
          const col = items.filter((i) => i.stage === stage);
          return (
            <div key={stage} className={`kcol ${over === stage ? "over" : ""}`} data-stage={stage}
              onDragOver={(e) => { e.preventDefault(); setOver(stage); }} onDragLeave={() => setOver(null)}
              onDrop={(e) => { e.preventDefault(); setOver(null); const id = drag ?? e.dataTransfer.getData("text/plain"); const it = items.find((i) => i.id === id); if (it && it.stage !== stage) void patch(id, { stage }); setDrag(null); }}>
              <h2>{label} <span className="count">{col.length}</span></h2>
              {col.map((i) => (
                <article key={i.id} className={`kcard ${drag === i.id ? "dragging" : ""}`} draggable data-testid="kcard"
                  onDragStart={(e) => { setDrag(i.id); e.dataTransfer.setData("text/plain", i.id); }} onDragEnd={() => setDrag(null)}>
                  <div className="kcard-top">
                    {i.score != null && <span className={`score small ${i.score >= 60 ? "hi" : i.score >= 40 ? "mid" : "lo"}`}>{i.score}%</span>}
                    <div><b>{i.title}</b><small className="muted">{[i.company, i.location].filter(Boolean).join(" · ")}</small></div>
                  </div>
                  <div className="kcard-actions">
                    <button className="icon-btn" aria-label="Move left" onClick={() => move(i, -1)} disabled={stage === COLS[0][0]}>←</button>
                    <button className="icon-btn" aria-label="Move right" onClick={() => move(i, 1)} disabled={stage === COLS[COLS.length - 1][0]}>→</button>
                    <button className="link small" onClick={() => setOpen(open === i.id ? null : i.id)}>{open === i.id ? "Close" : "Notes"}</button>
                    {i.url && <a className="link small" href={safeUrl(i.url)} target="_blank" rel="noopener noreferrer">Posting ↗</a>}
                    {i.analysis_id && i.job_id && <a className="link small" href={`/analysis/${i.analysis_id}?tab=jobs&job=${i.job_id}`}>Report</a>}
                  </div>
                  {open === i.id && <div className="kcard-notes">
                    <textarea rows={3} defaultValue={i.notes} placeholder="Notes: contacts, dates, follow-ups…" aria-label="Notes"
                      onBlur={(e) => { if (e.target.value !== i.notes) void patch(i.id, { notes: e.target.value }); }} />
                    <small className="muted">{i.history?.map((h) => `${h.stage} ${new Date(h.at * 1000).toLocaleDateString()}`).join(" → ")}</small>
                    <button className="link small danger" onClick={() => remove(i.id)}>Remove</button>
                  </div>}
                </article>
              ))}
            </div>
          );
        })}
      </div>
    </section>
  );
}

import type { SourceStat } from "../types";
import { StatusIcon } from "./Icons";

export function SearchProgress({ stage, sources, linkedin }: { stage: string; sources: SourceStat[]; linkedin?: { stage: string; done: number; total: number } | null }) {
  const done = sources.filter((s) => s.status !== "running").length;
  const pct = stage === "analyzing" ? 92 : stage === "done" ? 100 : sources.length ? Math.round((done / sources.length) * 85) : 5;
  return (
    <div className="card progress" aria-live="polite" data-testid="progress">
      <div className="p-top"><span>{stage === "analyzing" ? "Scoring your resume against every posting…" : stage === "ai" ? "Writing AI advice…" : `Collecting jobs (${done}/${sources.length} sources finished)…`}</span><span>{pct}%</span></div>
      <div className="bar"><i style={{ width: `${pct}%` }} /></div>
      {sources.length > 0 && (
        <ul className="checklist compact">
          {sources.map((s) => (
            <li key={s.id}>
              <StatusIcon s={s.status === "running" ? "running" : s.status === "done" ? (s.fetched ? "ok" : "warn") : "bad"} />
              <b>{s.name}</b>
              <span>
                {s.status === "running" ? (s.id === "linkedin" && linkedin ? `${linkedin.stage === "details" ? "reading descriptions" : "searching"} ${linkedin.done}/${linkedin.total}` : "fetching…")
                  : s.status === "done" ? `${s.fetched} fetched${s.kept !== undefined && s.status === "done" && stage !== "fetching" ? `, ${s.kept} relevant` : ""}${s.message ? ` · ${s.message}` : ""}`
                  : s.message}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

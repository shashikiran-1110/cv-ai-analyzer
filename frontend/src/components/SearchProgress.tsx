import { useEffect, useState } from "react";
import type { SourceStat } from "../types";
import { StatusIcon } from "./Icons";

const DROP_LABEL: Record<string, string> = {
  title: "different job title", location: "location", too_old: "too old", workplace: "workplace", job_type: "job type",
  experience: "seniority", duplicate: "duplicate", over_limit: "over your limit", no_title: "no title",
};
export const dropText = (d?: Record<string, number>, n = 3) =>
  Object.entries(d ?? {}).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]).slice(0, n).map(([k, v]) => `${v} ${DROP_LABEL[k] ?? k}`).join(", ");

const PHASES = [["fetching", "Fetching"], ["enriching", "Reading details"], ["analyzing", "Scoring"]] as const;

/** Live search progress: phases, elapsed time, every source's status and why postings were dropped. */
export function SearchProgress({ stage, sources, linkedin, enrich }: {
  stage: string; sources: SourceStat[]; linkedin?: { stage: string; done: number; total: number } | null; enrich?: { done: number; total: number } | null;
}) {
  const [t0] = useState(() => Date.now());
  const [now, setNow] = useState(Date.now());
  useEffect(() => { if (stage === "done") return; const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, [stage]);
  const done = sources.filter((s) => s.status !== "running").length;
  const phase = stage === "ai" ? "analyzing" : stage;
  const pct = phase === "analyzing" ? 92 : stage === "done" ? 100 : phase === "enriching" ? 75 + Math.round(((enrich?.done ?? 0) / Math.max(1, enrich?.total ?? 1)) * 12)
    : sources.length ? Math.round((done / sources.length) * 70) : 5;
  const secs = Math.round((now - t0) / 1000);
  const fetched = sources.reduce((n, s) => n + (s.fetched || 0), 0);
  return (
    <div className="card progress" aria-live="polite" data-testid="progress">
      <div className="phases">
        {PHASES.map(([k, l], i) => {
          const idx = PHASES.findIndex(([p]) => p === phase);
          return <span key={k} className={`phase ${k === phase ? "on" : idx > i || stage === "done" ? "done" : ""}`}>{i + 1}. {l}</span>;
        })}
        <span className="elapsed">{secs < 60 ? `${secs}s` : `${Math.floor(secs / 60)}m ${secs % 60}s`}</span>
      </div>
      <div className="p-top"><span>{phase === "analyzing" ? (stage === "ai" ? "Scoring, then writing AI advice…" : "Scoring your resume against every posting…")
        : phase === "enriching" ? `Reading full postings for missing details${enrich ? ` (${enrich.done}/${enrich.total})` : ""}…`
        : `Collecting jobs: ${done}/${sources.length} sources finished, ${fetched} postings so far`}</span><span>{pct}%</span></div>
      <div className="bar"><i style={{ width: `${pct}%` }} /></div>
      {sources.length > 0 && (
        <ul className="checklist compact">
          {sources.map((s) => (
            <li key={s.id}>
              <StatusIcon s={s.status === "running" ? "running" : s.status === "done" ? (s.fetched ? "ok" : "warn") : "bad"} />
              <b>{s.name}</b>
              <span>
                {s.status === "running" ? (s.id === "linkedin" && linkedin ? `${linkedin.stage === "details" ? "reading descriptions" : "searching"} ${linkedin.done}/${linkedin.total}` : "fetching…")
                  : s.status === "done" ? `${s.fetched} fetched${s.kept !== undefined && stage !== "fetching" ? `, ${s.kept} relevant${s.selected !== undefined ? `, ${s.selected} used` : ""}` : ""}`
                    + (dropText(s.dropped) ? ` · dropped: ${dropText(s.dropped)}` : "") + (s.message ? ` · ${s.message}` : "")
                  : s.message}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

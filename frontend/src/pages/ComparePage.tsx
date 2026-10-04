import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import type { ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { StatusIcon } from "../components/Icons";
import { Skeleton } from "../components/Skeleton";
import { qualifies, relTime } from "../components/table/JobsTable";
import type { Analysis, ScoredJob } from "../types";

const COMPONENTS: [keyof ScoredJob["components"], string][] = [["skills", "Skills"], ["requirements", "Requirements"], ["role", "Role fit"], ["experience", "Experience"], ["semantic", "Semantic"]];

/** 2–4 jobs side by side: score, components, gates, requirement coverage, gaps, salary. */
export function ComparePage() {
  const { aid = "" } = useParams();
  const [params] = useSearchParams();
  const ids = (params.get("ids") ?? "").split(",").filter(Boolean).slice(0, 4);
  const q = useQuery({ queryKey: ["analysis", aid], queryFn: () => api<Analysis>(`/api/analysis/${aid}`), staleTime: Infinity });
  if (q.isLoading) return <Skeleton rows={6} />;
  const a = q.data;
  if (!a) return <section className="empty-state"><h1>Report not found</h1><Link className="btn" to="/reports">All reports</Link></section>;
  const jobs = ids.map((id) => a.jobs.find((j) => j.id === id)).filter(Boolean) as ScoredJob[];
  const t = a.summary.threshold;
  if (jobs.length < 2) return (
    <section className="empty-state"><h1>Pick 2–4 jobs to compare</h1>
      <p className="muted">Select jobs in the report's Jobs table, then choose Compare.</p>
      <Link className="btn" to={`/analysis/${aid}?tab=jobs`}>Go to the jobs table</Link></section>);
  const best = (vals: number[]) => Math.max(...vals);
  const row = (label: string, cells: ReactNode[], bestIdx: number[] = []) => (
    <tr><th scope="row">{label}</th>{cells.map((c, i) => <td key={i} className={bestIdx.includes(i) ? "best" : ""}>{c}</td>)}</tr>
  );
  const idxOfMax = (vals: number[]) => { const m = best(vals); return vals.map((v, i) => (v === m ? i : -1)).filter((i) => i >= 0); };
  const scores = jobs.map((j) => j.score);
  return (
    <section aria-labelledby="h-compare">
      <div className="page-head">
        <div><Link className="link small" to={`/analysis/${aid}?tab=jobs`} style={{ marginTop: 0, marginBottom: 6 }}><ArrowLeft aria-hidden="true" />Back to the report</Link>
          <h1 id="h-compare">Compare {jobs.length} jobs</h1><p className="lead">Best value in each row is highlighted.</p></div>
      </div>
      <div className="cmp">
        <table>
          <thead><tr><th />{jobs.map((j) => <th key={j.id}><Link to={`/analysis/${aid}/job/${j.id}`}>{j.title}</Link><div className="small muted">{j.company}</div></th>)}</tr></thead>
          <tbody>
            {row("Match", jobs.map((j) => <span className={`score ${j.score >= t ? "hi" : j.score >= t - 15 ? "mid" : "lo"}`}>{j.score}%</span>), idxOfMax(scores))}
            {row("Status", jobs.map((j) => qualifies(j, t) ? <span className="tag q" style={{ marginLeft: 0 }}>Qualified</span> : j.score >= t ? <span className="tag gate" style={{ marginLeft: 0 }}>Fails a hard requirement</span> : <span className="tag nq" style={{ marginLeft: 0 }}>Below your bar</span>))}
            {COMPONENTS.map(([k, label]) => row(label, jobs.map((j) => `${j.components[k]}%`), idxOfMax(jobs.map((j) => j.components[k]))))}
            {row("Requirements met", jobs.map((j) => j.requirements.length ? `${j.requirements_met} of ${j.requirements.length}` : "—"),
              idxOfMax(jobs.map((j) => (j.requirements.length ? j.requirements_met / j.requirements.length : -1))))}
            {row("Hard requirements", jobs.map((j) => j.gates?.length ? <ul>{j.gates.map((g, i) => <li key={i}><StatusIcon s={g.status === "pass" ? "ok" : g.status === "fail" ? "bad" : "warn"} /> {g.label}</li>)}</ul> : "None found"))}
            {row("Missing (required)", jobs.map((j) => j.required_missing.length ? j.required_missing.join(", ") : "Nothing"), idxOfMax(jobs.map((j) => -j.required_missing.length)))}
            {row("Experience asked", jobs.map((j) => j.required_years != null ? `${j.required_years}+ yrs${j.required_years_inferred ? " (inferred)" : ""}` : "Not stated"))}
            {row("Location", jobs.map((j) => j.location || (j.remote ? "Remote" : "—")))}
            {row("Salary", jobs.map((j) => j.salary || "—"))}
            {row("Posted", jobs.map((j) => relTime(j.posted) || "—"))}
            {row("AI check", jobs.map((j) => j.deep ? `${j.deep.verdict || "done"} · ${j.deep.verified}/${j.deep.assessed} verified` : "Not run"))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

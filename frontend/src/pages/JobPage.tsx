import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useAi } from "../ai";
import { api, post } from "../api";
import { JobInsights, Posting, useJobDetail } from "../components/JobDrawer";
import { isTyping } from "../components/shell/ShellProvider";
import { Skeleton } from "../components/Skeleton";
import { SourceBadges } from "../components/SourceBadge";
import { relTime } from "../components/table/JobsTable";
import type { Analysis, DeepResult } from "../types";

/** Full job view: the posting (with requirement highlights) beside the analysis, resizable. */
export function JobPage() {
  const { aid = "", jobId = "" } = useParams();
  const ai = useAi();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ["analysis", aid], queryFn: () => api<Analysis>(`/api/analysis/${aid}`), staleTime: Infinity });
  const detail = useJobDetail(aid, jobId);
  const [flash, setFlash] = useState<string | null>(null);
  const [left, setLeft] = useState(() => { try { return Number(localStorage.getItem("cvm.split")) || 50; } catch { return 50; } });
  const box = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState(false);

  useEffect(() => {
    if (!flash) return;
    document.getElementById(`pl-${flash}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    const t = setTimeout(() => setFlash(null), 2200);
    return () => clearTimeout(t);
  }, [flash]);
  useEffect(() => {
    if (!drag) return;
    const move = (e: PointerEvent) => {
      const r = box.current?.getBoundingClientRect();
      if (r) setLeft(Math.max(28, Math.min(72, ((e.clientX - r.left) / r.width) * 100)));
    };
    const up = () => { setDrag(false); try { localStorage.setItem("cvm.split", String(Math.round(left))); } catch { /* blocked */ } };
    document.addEventListener("pointermove", move); document.addEventListener("pointerup", up);
    return () => { document.removeEventListener("pointermove", move); document.removeEventListener("pointerup", up); };
  }, [drag, left]);

  const a = q.data;
  const ordered = a ? [...a.jobs].sort((x, y) => y.score - x.score) : [];
  const idx = ordered.findIndex((j) => j.id === jobId);
  const prev = idx > 0 ? ordered[idx - 1] : null, next = idx >= 0 && idx < ordered.length - 1 ? ordered[idx + 1] : null;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e) || e.metaKey || e.ctrlKey || document.querySelector(".overlay, .cmdk-overlay")) return;
      if ((e.key === "k" || e.key === "ArrowLeft") && prev) navigate(`/analysis/${aid}/job/${prev.id}`, { replace: true });
      if ((e.key === "j" || e.key === "ArrowRight") && next) navigate(`/analysis/${aid}/job/${next.id}`, { replace: true });
      if (e.key === "Escape") navigate(`/analysis/${aid}?tab=jobs`);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [prev, next, aid, navigate]);

  if (q.isLoading) return <Skeleton rows={8} />;
  if (!a) return <section className="empty-state"><h1>Report not found</h1><p className="muted">{(q.error as Error)?.message || "This analysis expired."}</p><Link className="btn" to="/reports">All reports</Link></section>;
  const job = a.jobs.find((j) => j.id === jobId);
  if (!job) return <section className="empty-state"><h1>Job not found</h1><Link className="btn" to={`/analysis/${aid}?tab=jobs`}>Back to the report</Link></section>;

  const setData = (patch: Pick<Analysis, "summary" | "jobs">) => qc.setQueryData<Analysis>(["analysis", aid], (old) => old && { ...old, ...patch });
  async function onDeep(id: string): Promise<DeepResult> {
    const r = await post<Pick<Analysis, "summary" | "jobs"> & { deep: DeepResult }>(`/api/analysis/${aid}/deep/${id}`, {}, ai.headers);
    setData({ summary: r.summary, jobs: r.jobs });
    return r.deep;
  }

  return (
    <section aria-labelledby="h-job">
      <div className="page-head">
        <div style={{ minWidth: 0 }}>
          <Link className="link small" to={`/analysis/${aid}?tab=jobs`} style={{ marginTop: 0, marginBottom: 6 }}><ArrowLeft aria-hidden="true" />All jobs in this report</Link>
          <h1 id="h-job">{job.title}</h1>
          <div className="job-sub">{[job.company, job.location, job.salary, relTime(job.posted)].filter(Boolean).join(" · ")} <SourceBadges sources={job.sources} /></div>
        </div>
        <div className="actions">
          <span className="dt-meta">{idx + 1} of {ordered.length}</span>
          <button className="icon-btn" disabled={!prev} aria-label="Previous job (k)" title="Previous job (k)" onClick={() => prev && navigate(`/analysis/${aid}/job/${prev.id}`, { replace: true })}><ChevronLeft /></button>
          <button className="icon-btn" disabled={!next} aria-label="Next job (j)" title="Next job (j)" onClick={() => next && navigate(`/analysis/${aid}/job/${next.id}`, { replace: true })}><ChevronRight /></button>
        </div>
      </div>
      <div className="split" ref={box} style={{ gridTemplateColumns: `minmax(0, ${left}fr) 6px minmax(0, ${100 - left}fr)` }}>
        <div className="split-pane left">
          <div className="pane-title"><span>Posting</span><span>Click a matrix row to find it here</span></div>
          {detail?.description ? <Posting text={detail.description} reqs={job.requirements} gates={job.gates ?? []} flash={flash} />
            : <pre className="desc">{detail ? "No description available." : "Loading…"}</pre>}
        </div>
        <div className={`split-handle ${drag ? "drag" : ""}`} role="separator" aria-orientation="vertical" aria-label="Resize panes" tabIndex={0}
          aria-valuenow={Math.round(left)} aria-valuemin={28} aria-valuemax={72}
          onPointerDown={(e) => { e.preventDefault(); setDrag(true); }}
          onKeyDown={(e) => { if (e.key === "ArrowLeft") setLeft((v) => Math.max(28, v - 4)); if (e.key === "ArrowRight") setLeft((v) => Math.min(72, v + 4)); }} />
        <div className="split-pane">
          <JobInsights analysisId={aid} job={job} threshold={a.summary.threshold} onDeep={onDeep} onRescored={setData} onPick={setFlash} />
        </div>
      </div>
    </section>
  );
}

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAi } from "../ai";
import { JobsStep } from "../components/JobsStep";
import { SearchProgress } from "../components/SearchProgress";
import { Skeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { useRunEvents } from "../hooks/useRunEvents";
import { useSetup } from "../state/setup";
import type { SearchStatus } from "../types";
import { startAnalysis } from "./analyze";

export function SearchPage({ openDiagnose }: { openDiagnose: () => void }) {
  const { sid = "" } = useParams();
  const [params] = useSearchParams();
  const auto = params.get("auto") === "1";
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const ai = useAi();
  const { resume, opts } = useSetup();
  const [stage, setStage] = useState("fetching");
  const [err, setErr] = useState("");
  const started = useRef(false);

  const q = useQuery({
    queryKey: ["search", sid],
    queryFn: () => api<SearchStatus>(`/api/search/${sid}`),
    refetchInterval: (query) => (query.state.data?.status === "running" ? 4000 : false),  // SSE is primary; this is a safety net
  });
  const s = q.data;

  useRunEvents(s?.status === "running" ? sid : null, (e) => {
    if (e.type === "source.progress")
      qc.setQueryData<SearchStatus>(["search", sid], (old) => old && { ...old, sources: e.data.sources, linkedin: e.data.linkedin });
    if (e.type === "run.finished") void qc.invalidateQueries({ queryKey: ["search", sid] });
  }, () => void qc.invalidateQueries({ queryKey: ["search", sid] }));

  const notes = (st: SearchStatus) => [...(st.warnings ?? []), ...(st.sources ?? []).filter((x) => x.status === "error").map((x) => `${x.name}: ${x.message}`)];

  async function analyze(ids: string[] | null) {
    if (!resume.resumeId) { setErr("Your resume isn't loaded any more. Go back to setup and add it again."); return; }
    setStage(opts.wantAi && ai.usable ? "ai" : "analyzing");
    try {
      const a = await startAnalysis(sid, ids, resume, opts, ai);
      qc.setQueryData(["analysis", a.analysis_id], a);
      if (s) sessionStorage.setItem(`cvm.notes.${a.analysis_id}`, JSON.stringify(notes(s)));
      navigate(`/analysis/${a.analysis_id}`, { replace: auto });
    } catch (e) { setErr((e as Error).message); setStage("done"); toast((e as Error).message, "error"); }
  }

  useEffect(() => {
    if (!s || s.status !== "done" || !auto || started.current) return;
    if (!s.jobs?.length) return;
    started.current = true;
    void analyze(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s?.status, auto]);

  if (q.isLoading) return <section><h1>Collecting jobs…</h1><Skeleton rows={4} /></section>;
  if (q.isError) return (
    <section><h1>Search not found</h1><div className="alert error">{(q.error as Error).message}</div>
      <Link className="btn" to="/">← Back to setup</Link></section>);
  if (!s) return null;

  if (s.status === "running" || (auto && s.status === "done" && (s.jobs?.length ?? 0) > 0 && !err)) {
    return (
      <section aria-labelledby="h-run" className="enter">
        <h1 id="h-run">{s.status === "running" ? `Searching for “${s.query.title}”` : "Scoring your resume…"}</h1>
        <p className="lead">{s.status === "running" ? "Sources run in parallel; each one can fail without stopping the others." : "Comparing your resume with every requirement."}</p>
        <SearchProgress stage={s.status === "running" ? "fetching" : stage} sources={s.sources ?? []} linkedin={s.linkedin} />
        <Link className="link" to="/">Cancel and change setup</Link>
      </section>
    );
  }
  if (s.status === "error" || !s.jobs?.length) {
    return (
      <section className="enter">
        <h1>No jobs to analyze</h1>
        <div className="alert error" role="alert">
          <div>{s.error || "No relevant jobs found. Try a broader title, a different location, a longer time range, fewer filters or more sources."}</div>
          <div className="actions small-gap">
            <button className="btn small" onClick={openDiagnose}>Run connection check</button>
            <Link className="btn small" to="/">Change setup</Link>
          </div>
        </div>
        {(s.sources ?? []).length > 0 && <SearchProgress stage="done" sources={s.sources ?? []} />}
      </section>
    );
  }
  return (
    <>
      {err && <div className="alert error" role="alert">{err}</div>}
      <JobsStep search={s} searchId={sid} onBack={() => navigate("/")} analyze={(_, ids) => analyze(ids)} />
    </>
  );
}

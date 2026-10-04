import { Sparkles } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useAi } from "../ai";
import { api, ApiError, post } from "../api";
import { Feedback } from "../components/Feedback";
import { Skeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { Alert } from "../components/ui";
import { useRunEvents } from "../hooks/useRunEvents";
import type { AgentRun, AgentStep, Analysis, Projection, TailorEdit } from "../types";

const STEP_LABEL: Record<string, string> = {
  get_job_requirements: "Reading the job's requirements", get_profile_section: "Reading your resume",
  search_profile: "Looking for evidence in your resume", propose_edit: "Drafting an edit", ask_user: "Asking you a question",
  rescore: "Projecting the new score", finish: "Wrapping up",
};
const runKey = (aid: string, job: string) => `cvm.tailor.${aid}.${job}`;

/** Tailoring Agent + diff editor (ROADMAP §8.5, §9.5): AI proposes, the claim guard checks, you decide. */
export function TailorPage() {
  const { aid = "", jobId = "" } = useParams();
  const ai = useAi();
  const toast = useToast();
  const analysis = useQuery({ queryKey: ["analysis", aid], queryFn: () => api<Analysis>(`/api/analysis/${aid}`), staleTime: Infinity });
  const job = analysis.data?.jobs.find((j) => j.id === jobId);
  const [runId, setRunId] = useState<string | null>(() => { try { return sessionStorage.getItem(runKey(aid, jobId)); } catch { return null; } });
  const [run, setRun] = useState<AgentRun | null>(null);
  const [steps, setSteps] = useState<AgentStep[]>([]);
  const [drafts, setDrafts] = useState<Record<string, { text: string; accepted: boolean; agentText: string }>>({});
  const [check, setCheck] = useState<{ edits: TailorEdit[]; projection: Projection } | null>(null);
  const [answer, setAnswer] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const live = run?.status === "running";

  const load = (id: string) => api<AgentRun>(`/api/agent-runs/${id}`).then((r) => { setRun(r); setSteps(r.trace ?? []); })
    .catch((e) => { if ((e as ApiError).status === 404) { setRunId(null); try { sessionStorage.removeItem(runKey(aid, jobId)); } catch { /* */ } } });
  useEffect(() => { if (runId) void load(runId); }, [runId]); // eslint-disable-line react-hooks/exhaustive-deps

  useRunEvents(live ? runId : null, (e) => {
    if (e.type === "agent.step") setSteps((s) => [...s, e.data]);
    if (e.type === "agent.edit") setRun((r) => (r ? { ...r, edits: e.data.edits } : r));
    if (e.type === "agent.question" || e.type === "agent.done") { setRun(e.data); setSteps(e.data.trace ?? []); }
    if (e.type === "run.finished" && e.data.status === "error") { setErr(e.data.error || "The tailoring assistant failed."); if (runId) void load(runId); }
  }, () => { if (runId) void load(runId); });

  // every proposed edit gets an editable draft (accepted by default only if the claim guard passed)
  useEffect(() => {
    if (!run?.edits) return;
    setDrafts((d) => {
      const n = { ...d };
      run.edits.forEach((e) => {   // keep the user's own changes unless the assistant revised this edit since
        if (!n[e.bullet_id] || n[e.bullet_id].agentText !== e.new_text) n[e.bullet_id] = { text: e.new_text, accepted: !!e.ok, agentText: e.new_text };
      });
      return n;
    });
  }, [run?.edits]);

  const accepted = useMemo(() => Object.entries(drafts).filter(([, v]) => v.accepted && v.text.trim()).map(([bullet_id, v]) => ({ bullet_id, new_text: v.text.trim() })), [drafts]);
  const timer = useRef(0);
  const facts = run?.user_facts ?? "";     // your own answers count as evidence for the claim guard
  useEffect(() => {      // re-check the claim guard + projected score as the user edits/accepts
    if (!job) return;
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      post<{ edits: TailorEdit[]; projection: Projection }>(`/api/analysis/${aid}/tailor/${jobId}/preview`, { edits: accepted, user_facts: facts })
        .then(setCheck).catch(() => {});
    }, 400);
    return () => window.clearTimeout(timer.current);
  }, [accepted, aid, jobId, job, facts]);
  const violationsFor = (bid: string) => check?.edits.find((e) => e.bullet_id === bid)?.violations ?? [];
  const checked = !!check && accepted.every((e) => check.edits.some((c) => c.bullet_id === e.bullet_id && c.new_text === e.new_text));
  const blocking = !checked || accepted.some((e) => violationsFor(e.bullet_id).length > 0);

  async function start() {
    if (!ai.usable) return ai.openModal(true);
    setErr(""); setBusy(true); setSteps([]); setDrafts({});
    try {
      const r = await post<{ run_id: string }>(`/api/analysis/${aid}/tailor/${jobId}`, {}, ai.headers);
      try { sessionStorage.setItem(runKey(aid, jobId), r.run_id); } catch { /* */ }
      setRun({ id: r.run_id, kind: "tailoring", aid, job_id: jobId, status: "running", trace: [], edits: [] });
      setRunId(r.run_id);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  async function reply() {
    if (!runId || !answer.trim()) return;
    setBusy(true);
    try {
      await post(`/api/agent-runs/${runId}/answer`, { answer: answer.trim() }, ai.headers);
      setRun((r) => (r ? { ...r, status: "running", question: "" } : r)); setAnswer("");
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  async function download() {
    setBusy(true);
    try {
      const res = await fetch(`/api/analysis/${aid}/tailor/${jobId}/docx`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ edits: accepted, user_facts: facts }) });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `Export failed (HTTP ${res.status}).`);
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a"); a.href = url;
      a.download = (res.headers.get("content-disposition") || "").match(/filename="([^"]+)"/)?.[1] || "resume.docx"; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast("Tailored resume downloaded (.docx).", "ok");
    } catch (e) { toast((e as Error).message, "error"); } finally { setBusy(false); }
  }

  if (analysis.isPending) return <section className="enter"><h1>Tailor your resume</h1><Skeleton rows={6} /></section>;
  if (!job) return <section className="enter"><h1>Job not found</h1><Link className="btn" to={`/analysis/${aid}`}>Back to report</Link></section>;
  const proj = check?.projection;
  const edits = run?.edits ?? [];
  return (
    <section className="enter tailor-page" aria-labelledby="h-tailor">
      <div className="head-row">
        <div><h1 id="h-tailor">Tailor your resume</h1>
          <p className="lead">{job.title} · {job.company} · current match <b>{job.score}%</b></p></div>
        <div className="actions">
          <Link className="btn" to={`/analysis/${aid}?tab=jobs&job=${jobId}`}>← Back to job</Link>
          <button className="btn primary" onClick={download} disabled={busy || !accepted.length || blocking} data-testid="docx">Download .docx</button>
        </div>
      </div>
      <Alert kind="info">The assistant may only rephrase what's already on your resume or what you tell it. Every edit runs through a claim guard: new skills, employers, titles, degrees, dates or numbers are flagged in red and can't be exported until fixed.</Alert>
      {err && <Alert>{err}</Alert>}

      <div className="tailor-grid">
        <aside className="card agent-card">
          <h2>Assistant</h2>
          {!run && <><p className="muted">It reads the job's requirements and your bullets, then proposes up to 8 edits with reasons.</p>
            <button className="btn primary" onClick={start} disabled={busy} data-testid="start-tailor">{ai.usable ? <><Sparkles aria-hidden="true" />Start tailoring</> : "Add an AI key to start"}</button></>}
          {run && <ol className="steps">
            {steps.filter((s) => s.kind === "tool" || s.kind === "answer").map((s, i) => (
              <li key={i} className={s.error ? "err" : ""}><span className="dot" aria-hidden="true" />
                {s.kind === "answer" ? <>You answered: <em>{s.output}</em></> : STEP_LABEL[s.tool ?? ""] ?? s.tool}</li>))}
            {live && <li className="pending"><span className="dot pulse" aria-hidden="true" /> Thinking…</li>}
          </ol>}
          {run?.status === "needs_input" && (
            <div className="question" data-testid="agent-question">
              <b>{run.question}</b>
              <textarea rows={3} value={answer} onChange={(e) => setAnswer(e.target.value)} placeholder="Your answer (facts only; it will be used in the edit)" maxLength={2000} />
              <button className="btn small primary" onClick={reply} disabled={busy || !answer.trim()}>Send answer</button>
            </div>)}
          {run?.final && run.status !== "running" && <p className="final"><b>Summary:</b> {run.final}</p>}
          {run && run.status !== "running" && <button className="link" onClick={start} disabled={busy}>Start over</button>}
        </aside>

        <div>
          <div className={`card proj ${proj && proj.score_after > proj.score_before ? "up" : ""}`} data-testid="projection">
            <div><small>Projected match with accepted edits</small>
              <div className="proj-num">{proj ? <>{proj.score_before}% → <b>{proj.score_after}%</b></> : `${job.score}%`}</div></div>
            {proj && proj.changed.length > 0 && <ul className="small">{proj.changed.map((c, i) => <li key={i}>{c.requirement}: {c.before} → <b>{c.after}</b></li>)}</ul>}
          </div>
          {edits.length === 0 && run && !live && <p className="muted">No edits proposed.</p>}
          {edits.map((e) => {
            const d = drafts[e.bullet_id] ?? { text: e.new_text, accepted: !!e.ok, agentText: e.new_text };
            const v = d.accepted ? violationsFor(e.bullet_id) : e.violations;
            return (
              <div key={e.bullet_id} className={`card diff ${d.accepted ? "on" : ""} ${v.length ? "bad" : ""}`} data-testid="diff">
                <div className="diff-head"><small className="muted">{e.role}{e.requirement_ids?.length ? ` · for ${e.requirement_ids.join(", ")}` : ""}</small>
                  <label className="check small"><input type="checkbox" checked={d.accepted} onChange={(x) => setDrafts({ ...drafts, [e.bullet_id]: { ...d, accepted: x.target.checked } })} /> Accept</label></div>
                <div className="diff-cols">
                  <div className="old"><small>Original</small><p>{e.original || <em>New bullet</em>}</p></div>
                  <div className="new"><small>Proposed (editable)</small>
                    <textarea rows={3} value={d.text} onChange={(x) => setDrafts({ ...drafts, [e.bullet_id]: { ...d, text: x.target.value } })} /></div>
                </div>
                <div className="actions" style={{ gap: 4 }}>{e.rationale && <small className="muted">Why: {e.rationale}</small>}
                  <Feedback target={{ kind: "tailoring_edit", analysisId: aid, jobId, itemId: e.bullet_id, output: JSON.stringify({ original: e.original, proposed: e.new_text, violations: e.violations }) }} label="this edit" /></div>
                {v.length > 0 && <ul className="violations">{v.map((x) => <li key={x}>✕ {x}</li>)}</ul>}
              </div>);
          })}
        </div>
      </div>
    </section>
  );
}

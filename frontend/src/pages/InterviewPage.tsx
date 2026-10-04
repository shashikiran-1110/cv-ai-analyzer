import { Sparkles } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useAi } from "../ai";
import { api, post } from "../api";
import { Feedback as RateAi } from "../components/Feedback";
import { Skeleton } from "../components/Skeleton";
import { Alert, Meter } from "../components/ui";
import type { Analysis, PracticeEntry, PracticeHistory } from "../types";

const FOCUS: Record<string, string> = { gap: "probes a gap", strength: "shows a strength", general: "general" };

/** Interview Coach v1 (ROADMAP §8.8): questions from the job's requirements, rubric feedback per answer. */
export function InterviewPage() {
  const { aid = "", jobId = "" } = useParams();
  const ai = useAi();
  const qc = useQueryClient();
  const analysis = useQuery({ queryKey: ["analysis", aid], queryFn: () => api<Analysis>(`/api/analysis/${aid}`), staleTime: Infinity });
  const hist = useQuery({ queryKey: ["practice", aid, jobId], queryFn: () => api<PracticeHistory>(`/api/analysis/${aid}/interview/${jobId}`) });
  const [sel, setSel] = useState<string | null>(null);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [last, setLast] = useState<PracticeEntry | null>(null);
  const job = analysis.data?.jobs.find((j) => j.id === jobId);

  async function generate() {
    if (!ai.usable) return ai.openModal(true);
    setBusy(true); setErr("");
    try { qc.setQueryData(["practice", aid, jobId], await post<PracticeHistory>(`/api/analysis/${aid}/interview/${jobId}/questions`, {}, ai.headers)); setSel(null); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  async function submit() {
    if (!sel) return;
    if (!ai.usable) return ai.openModal(true);
    setBusy(true); setErr("");
    try {
      const e = await post<PracticeEntry>(`/api/analysis/${aid}/interview/${jobId}/answer`, { question_id: sel, answer }, ai.headers);
      setLast(e); setAnswer("");
      qc.setQueryData<PracticeHistory>(["practice", aid, jobId], (h) => (h ? { ...h, answers: [...h.answers, e] } : h));
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }

  if (analysis.isPending || hist.isPending) return <section className="enter"><h1>Interview practice</h1><Skeleton rows={6} /></section>;
  if (!job) return <section className="enter"><h1>Job not found</h1><Link className="btn" to={`/analysis/${aid}`}>Back to report</Link></section>;
  const h = hist.data ?? { questions: [], answers: [] };
  const q = h.questions.find((x) => x.id === sel);
  const reqText = (id: string) => job.requirements.find((r) => r.id === id)?.text;
  return (
    <section className="enter interview-page" aria-labelledby="h-int">
      <div className="head-row">
        <div><h1 id="h-int">Interview practice</h1><p className="lead">{job.title} · {job.company}</p></div>
        <div className="actions"><Link className="btn" to={`/analysis/${aid}?tab=jobs&job=${jobId}`}>← Back to job</Link>
          <button className="btn primary" onClick={generate} disabled={busy} data-testid="gen-questions">{h.questions.length ? "New questions" : <><Sparkles aria-hidden="true" />Generate questions</>}</button></div>
      </div>
      {!ai.usable && <Alert kind="info">Add an AI key to generate questions and get feedback. <button className="link" onClick={() => ai.openModal(true)}>Open AI settings</button></Alert>}
      {err && <Alert>{err}</Alert>}
      <div className="cols">
        <div className="card">
          <h2>Questions</h2>
          {h.questions.length === 0 && <p className="muted">Questions are built from this job's requirements, weighted toward the ones your resume doesn't clearly show yet.</p>}
          <ol className="qlist">{h.questions.map((x) => (
            <li key={x.id}><button className={`q ${sel === x.id ? "on" : ""}`} onClick={() => { setSel(x.id); setLast(null); }}>
              <span>{x.question}</span><small className={`focus f-${x.focus}`}>{FOCUS[x.focus]}{x.requirement_id && reqText(x.requirement_id) ? ` · ${reqText(x.requirement_id)}` : ""}</small></button></li>))}</ol>
        </div>
        <div className="card">
          {!q ? <p className="muted">Pick a question, answer it as you would out loud, and get feedback on structure, specificity and relevance.</p> : <>
            <h2>{q.question}</h2>
            <small className="muted">A good answer: {q.what_good_looks_like}</small>
            <textarea rows={7} value={answer} onChange={(e) => setAnswer(e.target.value)} maxLength={4000} placeholder="Situation → task → what you did → result (with numbers if you have them)" aria-label="Your answer" />
            <button className="btn primary" onClick={submit} disabled={busy || answer.trim().length < 20} data-testid="get-feedback">{busy ? "Scoring…" : "Get feedback"}</button>
          </>}
          {last && <Feedback e={last} />}
        </div>
      </div>
      {h.answers.length > 0 && <div className="card"><h2>Practice history</h2>
        <ul className="history">{[...h.answers].reverse().map((e, i) => (
          <li key={i}><details><summary><b>{e.question}</b> <span className="muted">· {Object.values(e.feedback.scores).reduce((a, b) => a + b, 0)}/15 · {new Date(e.at * 1000).toLocaleString()}</span></summary><Feedback e={e} /></details></li>))}</ul>
      </div>}
    </section>
  );
}

function Feedback({ e }: { e: PracticeEntry }) {
  const f = e.feedback;
  return (
    <div className="feedback enter" data-testid="feedback">
      {(["structure", "specificity", "relevance"] as const).map((k) => (
        <div className="comp" key={k}><span>{k[0].toUpperCase() + k.slice(1)}</span><Meter value={f.scores[k] * 20} tone={f.scores[k] >= 4 ? "good" : f.scores[k] <= 2 ? "warn" : "brand"} /><span>{f.scores[k]}/5</span></div>))}
      <div className="cols tight">
        <div><h4>Worked well</h4><ul className="bullets">{f.strengths.map((x, i) => <li key={i}>{x}</li>)}</ul></div>
        <div><h4>Improve</h4><ul className="bullets">{f.improvements.map((x, i) => <li key={i}>{x}</li>)}</ul></div>
      </div>
      <h4 style={{ display: "flex", alignItems: "center" }}>Stronger version<RateAi target={{ kind: "interview_feedback", itemId: e.question_id, output: JSON.stringify(f) }} label="this feedback" /></h4>
      <blockquote className="evidence">{f.stronger_answer}</blockquote>
      {f.violations.length > 0 && <ul className="violations">{f.violations.map((v) => <li key={v}>✕ {v}</li>)}</ul>}
    </div>
  );
}

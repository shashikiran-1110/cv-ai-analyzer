import { useEffect, useRef, useState } from "react";
import { useAi } from "../ai";
import { post, streamPost } from "../api";
import type { ChatMsg, ScoredJob } from "../types";
import { CopyButton, Markdown } from "./Markdown";
import { Alert } from "./ui";

const SUGGESTIONS = [
  "Which 3 skills would unlock the most of these jobs, and why?",
  "Rewrite my resume summary for my best-matching role.",
  "Give me a 30-day plan to become a stronger candidate for these jobs.",
  "What are the biggest weaknesses a recruiter would see in my resume?",
  "Which of these jobs should I apply to first, and which should I skip?",
];

type Meta = { tools?: string[]; unverified?: string[] };
const TOOL_LABEL: Record<string, string> = { list_jobs: "listed jobs", get_job_explanation: "explained a job", what_if: "ran a what-if",
  get_profile: "read your profile", get_market_stats: "read market stats" };

/** Resolve a run's final event (agent.done) over SSE, reporting each tool step. */
function waitRun(runId: string, onStep: (tool: string) => void): Promise<any> {
  return new Promise((resolve, reject) => {
    const es = new EventSource(`/api/runs/${runId}/events`);
    let result: any = null;
    es.addEventListener("agent.step", (ev) => { try { const d = JSON.parse((ev as MessageEvent).data); if (d.tool) onStep(d.tool); } catch { /* */ } });
    es.addEventListener("agent.done", (ev) => { result = JSON.parse((ev as MessageEvent).data); });
    es.addEventListener("run.finished", (ev) => {
      es.close();
      const d = JSON.parse((ev as MessageEvent).data || "{}");
      if (d.status === "error" || !result) reject(new Error(d.error || "The coach couldn't answer.")); else resolve(result);
    });
    es.onerror = () => { if (es.readyState === EventSource.CLOSED && !result) reject(new Error("Lost connection to the coach.")); };
  });
}

export function AssistantTab({ analysisId, jobs }: { analysisId: string; jobs: ScoredJob[] }) {
  const ai = useAi();
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [jobId, setJobId] = useState("");
  const [mode, setMode] = useState<"coach" | "writer">("coach");
  const [meta, setMeta] = useState<Record<number, Meta>>({});
  const [live, setLive] = useState<string[]>([]);
  const ctl = useRef<AbortController | null>(null);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "nearest" }); }, [msgs]);
  useEffect(() => () => ctl.current?.abort(), []);

  async function send(text: string) {
    const q = text.trim();
    if (!q || busy) return;
    if (!ai.usable) return ai.openModal(true);
    setErr(""); setInput("");
    const history: ChatMsg[] = [...msgs, { role: "user", content: q }];
    setMsgs([...history, { role: "assistant", content: "" }]);
    const c = new AbortController(); ctl.current = c; setBusy(true);
    let acc = "";
    if (mode === "coach") {
      setLive([]);
      try {
        const { run_id } = await post<{ run_id: string }>(`/api/analysis/${analysisId}/coach`, { messages: history }, ai.headers);
        const out = await waitRun(run_id, (t) => setLive((l) => [...l, t]));
        setMsgs([...history, { role: "assistant", content: out.answer }]);
        setMeta((m) => ({ ...m, [history.length]: { tools: out.tools_used, unverified: out.numbers_unverified } }));
      } catch (e) { setErr((e as Error).message); setMsgs(history); }
      finally { setBusy(false); setLive([]); }
      return;
    }
    try {
      for await (const t of streamPost(`/api/analysis/${analysisId}/chat`, { messages: history, job_id: jobId || null }, ai.headers, c.signal)) {
        acc += t;
        setMsgs([...history, { role: "assistant", content: acc }]);
      }
    } catch (e) {
      setErr((e as Error).message);
      if (!acc) setMsgs(history);
    } finally { setBusy(false); }
  }

  return (
    <div className="card chat">
      <div className="toolbar">
        <h2 className="inline">AI career assistant</h2>
        <div className="seg narrow" role="radiogroup" aria-label="Assistant mode">
          <button type="button" role="radio" aria-checked={mode === "coach"} onClick={() => setMode("coach")} title="Looks facts up with tools; numbers are checked against the engine">Coach</button>
          <button type="button" role="radio" aria-checked={mode === "writer"} onClick={() => setMode("writer")} title="Streams drafts (summaries, letters) from your resume and the analysis">Writer</button>
        </div>
        {mode === "writer" && <label className="inline-field"><small>Focus on</small>
          <select value={jobId} onChange={(e) => setJobId(e.target.value)} aria-label="Focus job">
            <option value="">All jobs (overall)</option>
            {jobs.map((j) => <option key={j.id} value={j.id}>{j.score}% · {j.title} @ {j.company}</option>)}
          </select>
        </label>}
        {msgs.length > 0 && <button className="btn small" onClick={() => { ctl.current?.abort(); setMsgs([]); setErr(""); }}>New chat</button>}
      </div>
      {!ai.usable && <Alert kind="info">Add your OpenAI or Anthropic API key to chat with the assistant. <button className="link" onClick={() => ai.openModal(true)}>Open AI settings</button></Alert>}
      <div className="chat-log" aria-live="polite">
        {msgs.length === 0 && (
          <div className="chat-empty">
            <p className="muted">{mode === "coach" ? "The coach looks things up in your analysis with tools (job list, explanations, what-if re-scoring, market stats); any number it states that isn't in that data is flagged."
              : `Writer mode drafts text from your resume and the analysis${jobId ? " and the focused job" : ""}.`}</p>
            <div className="toggles">{SUGGESTIONS.map((s) => <button key={s} className="toggle" onClick={() => send(s)} disabled={busy}>{s}</button>)}</div>
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={`bubble ${m.role}`}>
            {m.role === "assistant" ? (m.content ? <Markdown text={m.content} /> : <span className="typing">{live.length ? `Thinking… (${live.map((t) => TOOL_LABEL[t] ?? t).join(", ")})` : "Thinking…"}</span>) : <p>{m.content}</p>}
            {meta[i]?.tools && meta[i].tools!.length > 0 && <div className="tool-chips">{meta[i].tools!.map((t, k) => <span key={k} className="chip">{TOOL_LABEL[t] ?? t}</span>)}</div>}
            {meta[i]?.unverified && meta[i].unverified!.length > 0 && <small className="warn-text" data-testid="unverified">Numbers not found in the app's data: {meta[i].unverified!.join(", ")}. Double-check them.</small>}
            {m.role === "assistant" && m.content && !(busy && i === msgs.length - 1) && <CopyButton text={m.content} />}
          </div>
        ))}
        <div ref={end} />
      </div>
      {err && <Alert>{err}</Alert>}
      <form className="chat-input" onSubmit={(e) => { e.preventDefault(); void send(input); }}>
        <textarea rows={2} value={input} maxLength={4000} placeholder="Ask the assistant…  (Enter to send, Shift+Enter for a new line)" aria-label="Message"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(input); } }} />
        {busy ? <button type="button" className="btn" onClick={() => ctl.current?.abort()}>Stop</button>
          : <button className="btn primary" disabled={!input.trim()}>Send</button>}
      </form>
      <small className="fine">AI can make mistakes. Check facts before using any text, and never include details that aren't true.</small>
    </div>
  );
}

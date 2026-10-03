import { useEffect, useRef, useState } from "react";
import { useAi } from "../ai";
import { streamPost } from "../api";
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

export function AssistantTab({ analysisId, jobs }: { analysisId: string; jobs: ScoredJob[] }) {
  const ai = useAi();
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [jobId, setJobId] = useState("");
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
        <label className="inline-field"><small>Focus on</small>
          <select value={jobId} onChange={(e) => setJobId(e.target.value)} aria-label="Focus job">
            <option value="">All jobs (overall)</option>
            {jobs.map((j) => <option key={j.id} value={j.id}>{j.score}% · {j.title} @ {j.company}</option>)}
          </select>
        </label>
        {msgs.length > 0 && <button className="btn small" onClick={() => { ctl.current?.abort(); setMsgs([]); setErr(""); }}>New chat</button>}
      </div>
      {!ai.usable && <Alert kind="info">Add your OpenAI or Anthropic API key to chat with the assistant. <button className="link" onClick={() => ai.openModal(true)}>Open AI settings</button></Alert>}
      <div className="chat-log" aria-live="polite">
        {msgs.length === 0 && (
          <div className="chat-empty">
            <p className="muted">Ask anything about your resume, these jobs, or your next steps. The assistant sees your resume and the analysis{jobId ? " and the focused job" : ""}.</p>
            <div className="toggles">{SUGGESTIONS.map((s) => <button key={s} className="toggle" onClick={() => send(s)} disabled={busy}>{s}</button>)}</div>
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={`bubble ${m.role}`}>
            {m.role === "assistant" ? (m.content ? <Markdown text={m.content} /> : <span className="typing">Thinking…</span>) : <p>{m.content}</p>}
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

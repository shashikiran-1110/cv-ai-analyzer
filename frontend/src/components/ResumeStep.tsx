import { useRef, useState } from "react";
import { useAi } from "../ai";
import { ApiError, api } from "../api";
import type { Analysis } from "../types";
import { SkillPicker } from "./SkillPicker";
import { Alert } from "./ui";

const MAX = 10 * 1024 * 1024;

export function ResumeStep({ searchId, jobIds, defaultThreshold, onBack, onDone }: {
  searchId: string; jobIds: string[]; defaultThreshold: number; onBack: () => void;
  onDone: (a: Analysis, threshold: number) => void;
}) {
  const ai = useAi();
  const [mode, setMode] = useState<"pdf" | "paste">("pdf");
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [extra, setExtra] = useState<string[]>([]);
  const [threshold, setThreshold] = useState(defaultThreshold);
  const [wantAi, setWantAi] = useState(true);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const input = useRef<HTMLInputElement>(null);

  function pick(f: File | undefined) {
    setErr("");
    if (!f) return;
    if (!(f.type === "application/pdf" || /\.pdf$/i.test(f.name))) return setErr("Please choose a PDF file.");
    if (f.size === 0) return setErr("That file is empty.");
    if (f.size > MAX) return setErr("That PDF is larger than 10 MB.");
    setFile(f);
  }
  const ready = mode === "pdf" ? !!file : text.trim().length >= 100;
  const aiOn = wantAi && ai.usable;

  async function analyze() {
    setErr(""); setBusy(true);
    const fd = new FormData();
    fd.append("search_id", searchId);
    if (mode === "pdf" && file) fd.append("resume", file); else fd.append("resume_text", text);
    fd.append("threshold", String(threshold));
    fd.append("use_ai", aiOn ? "true" : "false");
    fd.append("job_ids", JSON.stringify(jobIds));
    fd.append("extra_skills", JSON.stringify(extra));
    try {
      const a = await api<Analysis>("/api/analyze", { method: "POST", body: fd, headers: aiOn ? ai.headers : {} });
      onDone(a, threshold);
    } catch (e) { setErr(e instanceof ApiError ? e.message : "Analysis failed."); }
    finally { setBusy(false); }
  }

  return (
    <section aria-labelledby="h-resume">
      <div className="head-row">
        <div><h1 id="h-resume">Your resume</h1><p className="lead">Analyzing {jobIds.length} jobs. Your resume is read in memory only and isn't stored on disk.</p></div>
        <div className="actions"><button className="btn" onClick={onBack}>← Back to jobs</button></div>
      </div>
      <div className="card">
        <div className="seg narrow" role="tablist" aria-label="Resume input">
          <button role="tab" type="button" aria-selected={mode === "pdf"} aria-checked={mode === "pdf"} onClick={() => setMode("pdf")}>Upload PDF</button>
          <button role="tab" type="button" aria-selected={mode === "paste"} aria-checked={mode === "paste"} onClick={() => setMode("paste")}>Paste text</button>
        </div>
        {mode === "pdf" ? (
          <label className={`drop ${over ? "over" : ""} ${file ? "has" : ""}`} tabIndex={0}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.current?.click(); } }}
            onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
            onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files[0]); }}>
            <input ref={input} type="file" accept="application/pdf,.pdf" hidden onChange={(e) => pick(e.target.files?.[0])} />
            <div className="drop-icon" aria-hidden="true">⇪</div>
            <div>{file ? <><b>{file.name}</b> · {(file.size / 1024).toFixed(0)} KB · click to replace</> : <><b>Drop your PDF here</b> or click to browse</>}</div>
            <small>PDF up to 10 MB (text-based, not a scan)</small>
          </label>
        ) : (
          <label className="field"><span>Resume text</span>
            <textarea rows={12} value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste your resume here…" maxLength={40000} />
            <small>{text.trim().length} characters{text.trim().length < 100 ? " (need at least 100)" : ""}</small>
          </label>
        )}

        <div className="opts">
          <div className="field">
            <span>Skills you have that aren't on your resume <small>(optional)</small></span>
            <SkillPicker value={extra} onChange={setExtra} />
            <small>Counted as yours when matching. You can also try “what if I learned X” later in the report.</small>
          </div>
          <label className="field">
            <span>Count a job as “qualified” at <b>{threshold}%</b> match or higher</span>
            <input type="range" min={30} max={90} step={5} value={threshold} onChange={(e) => setThreshold(+e.target.value)} />
            <small>Adjustable later on the report; it updates instantly.</small>
          </label>
          <div className="ai-row">
            <label className="check">
              <input type="checkbox" checked={wantAi} disabled={!ai.usable} onChange={(e) => setWantAi(e.target.checked)} />
              <span><b>AI-written advice</b>{ai.usable
                ? <> using {ai.settings.key ? (ai.settings.provider === "openai" ? "OpenAI" : "Anthropic") : `the server's ${ai.serverAi}`} key. Your resume text is sent to that provider. Untick to keep it local.</>
                : <> needs an API key.</>}</span>
            </label>
            {!ai.usable && <button type="button" className="btn small" onClick={() => ai.openModal(true)}>Add AI key</button>}
          </div>
        </div>
        {err && <Alert>{err}</Alert>}
        <div className="actions end"><button className="btn primary" disabled={!ready || busy} onClick={analyze}>{busy ? (aiOn ? "Analyzing with AI…" : "Analyzing…") : "Analyze match"}</button></div>
      </div>
    </section>
  );
}

import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { ResumePreview } from "../types";
import { SkillPicker } from "./SkillPicker";
import { Alert } from "./ui";

export interface ResumeState { mode: "pdf" | "paste"; file: File | null; text: string; extra: string[]; preview: ResumePreview | null }
export const EMPTY_RESUME: ResumeState = { mode: "pdf", file: null, text: "", extra: [], preview: null };
const MAX = 10 * 1024 * 1024;

export function resumeReady(r: ResumeState) { return !!r.preview && (r.mode === "pdf" ? !!r.file : r.text.trim().length >= 100); }

export function ResumeCard({ value, onChange }: { value: ResumeState; onChange: (r: ResumeState) => void }) {
  const [over, setOver] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [showExtra, setShowExtra] = useState(value.extra.length > 0);
  const input = useRef<HTMLInputElement>(null);
  const seq = useRef(0);
  const latest = useRef(value);
  latest.current = value;

  async function preview(next: ResumeState) {
    const id = ++seq.current;
    const fd = new FormData();
    if (next.mode === "pdf" && next.file) fd.append("resume", next.file); else fd.append("resume_text", next.text);
    setBusy(true); setErr("");
    try {
      const p = await api<ResumePreview>("/api/resume/preview", { method: "POST", body: fd });
      if (id === seq.current) onChange({ ...latest.current, preview: p });
    } catch (e) {
      if (id === seq.current) { setErr((e as Error).message); onChange({ ...latest.current, preview: null }); }
    } finally { if (id === seq.current) setBusy(false); }
  }

  function pick(f: File | undefined) {
    setErr("");
    if (!f) return;
    if (!(f.type === "application/pdf" || /\.pdf$/i.test(f.name))) return setErr("Please choose a PDF file.");
    if (f.size === 0) return setErr("That file is empty.");
    if (f.size > MAX) return setErr("That PDF is larger than 10 MB.");
    const next = { ...value, mode: "pdf" as const, file: f, preview: null };
    onChange(next); void preview(next);
  }

  // debounce previews of pasted text
  useEffect(() => {
    if (value.mode !== "paste") return;
    if (value.text.trim().length < 100) { if (value.preview) onChange({ ...value, preview: null }); return; }
    const t = setTimeout(() => void preview(value), 700);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value.text, value.mode]);

  const p = value.preview;
  return (
    <div className="card setup-card">
      <div className="card-head"><span className="num">1</span><div><h2>Your resume</h2><small>PDF or pasted text · read in memory, never stored</small></div></div>
      <div className="seg narrow" role="tablist" aria-label="Resume input">
        {(["pdf", "paste"] as const).map((m) => (
          <button key={m} role="tab" type="button" aria-selected={value.mode === m} aria-checked={value.mode === m}
            onClick={() => { setErr(""); const next = { ...value, mode: m, preview: null }; onChange(next); if (m === "pdf" && value.file) void preview(next); }}>
            {m === "pdf" ? "Upload PDF" : "Paste text"}
          </button>
        ))}
      </div>
      {value.mode === "pdf" ? (
        <label className={`drop ${over ? "over" : ""} ${value.file ? "has" : ""}`} tabIndex={0} data-testid="dropzone"
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.current?.click(); } }}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files[0]); }}>
          <input ref={input} type="file" accept="application/pdf,.pdf" hidden onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }} />
          <div className="drop-icon" aria-hidden="true">⇪</div>
          <div>{value.file ? <><b>{value.file.name}</b> · {(value.file.size / 1024).toFixed(0)} KB · click to replace</> : <><b>Drop your CV / resume PDF here</b> or click to browse</>}</div>
          <small>Text-based PDF up to 10 MB (scanned images can't be read; paste text instead)</small>
        </label>
      ) : (
        <label className="field"><span>Resume text</span>
          <textarea rows={9} value={value.text} onChange={(e) => onChange({ ...value, text: e.target.value })} placeholder="Paste your resume here…" maxLength={40000} />
          <small>{value.text.trim().length} characters{value.text.trim().length < 100 ? " (need at least 100)" : ""}</small>
        </label>
      )}
      {busy && <p className="muted">Reading your resume…</p>}
      {err && <Alert>{err}</Alert>}
      {p && !busy && (
        <div className="preview" data-testid="resume-preview">
          <div className="preview-head"><b>✓ Resume read</b><small>{p.words} words · ~{p.years || "?"} yrs experience · {p.education ?? "no degree found"}</small></div>
          <div className="chips">{p.skills.slice(0, 24).map((s) => <span className="chip ok" key={s}>{s}</span>)}
            {p.skills.length > 24 && <span className="chip">+{p.skills.length - 24} more</span>}
            {p.skills.length === 0 && <span className="muted">No known skills detected; matching will rely on keywords.</span>}</div>
          <small className="muted">These are the skills the matcher sees. If something's missing, add it below.</small>
        </div>
      )}
      <button type="button" className="link" onClick={() => setShowExtra(!showExtra)} aria-expanded={showExtra}>{showExtra ? "▾" : "▸"} Skills you have that aren't on your resume{value.extra.length ? ` (${value.extra.length})` : ""}</button>
      {showExtra && <SkillPicker value={value.extra} onChange={(extra) => onChange({ ...value, extra })} />}
    </div>
  );
}

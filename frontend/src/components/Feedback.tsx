import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import { post } from "../api";
import type { FeedbackKind, ScoredJob, Summary } from "../types";
import { useToast } from "./Toast";

export interface FeedbackTarget { kind: FeedbackKind; analysisId?: string; jobId?: string; itemId?: string; output?: string; model?: string }
type Rescored = { summary: Summary; jobs: ScoredJob[] };

export function sendFeedback(t: FeedbackTarget, extra: { rating?: -1 | 0 | 1; correction?: Record<string, unknown>; comment?: string }) {
  return post<{ id: number } & Partial<Rescored>>("/api/feedback", {
    kind: t.kind, analysis_id: t.analysisId ?? "", job_id: t.jobId ?? "", item_id: (t.itemId ?? "").slice(0, 400),
    output: t.output ? t.output.slice(0, 20000) : null, model: t.model ?? "", rating: extra.rating ?? 0,
    correction: extra.correction ?? null, comment: extra.comment ?? "",
  });
}

/** 👍/👎 on an AI output. A thumbs-down asks (optionally) what was wrong; both feed the eval datasets. */
export function Feedback({ target, label = "this answer" }: { target: FeedbackTarget; label?: string }) {
  const toast = useToast();
  const [rating, setRating] = useState<-1 | 0 | 1>(0);
  const [open, setOpen] = useState(false);
  const [comment, setComment] = useState("");
  const [sent, setSent] = useState(false);
  async function rate(r: -1 | 1) {
    setRating(r);
    if (r === -1) { setOpen(true); return; }
    try { await sendFeedback(target, { rating: r }); setSent(true); } catch (e) { toast((e as Error).message, "error"); setRating(0); }
  }
  async function submit() {
    try { await sendFeedback(target, { rating: -1, comment }); setSent(true); setOpen(false); }
    catch (e) { toast((e as Error).message, "error"); }
  }
  return (
    <>
      <span className="fb" role="group" aria-label={`Rate ${label}`}>
        <button className={`icon-btn up ${rating === 1 ? "on" : ""}`} aria-pressed={rating === 1} aria-label="Helpful" title="Helpful" onClick={() => rate(1)} disabled={sent}><ThumbsUp /></button>
        <button className={`icon-btn down ${rating === -1 ? "on" : ""}`} aria-pressed={rating === -1} aria-label="Not helpful" title="Not helpful or wrong" onClick={() => rate(-1)} disabled={sent}><ThumbsDown /></button>
        {sent && <span className="fb-thanks">Thanks, noted.</span>}
      </span>
      {open && !sent && (
        <div className="fb-form">
          <label className="field"><span>What was wrong? <small>(optional, helps us evaluate the AI)</small></span>
            <textarea value={comment} onChange={(e) => setComment(e.target.value)} maxLength={2000} rows={2} placeholder="e.g. it claimed I have Kubernetes experience" /></label>
          <div className="actions"><button className="btn small primary" onClick={submit}>Send</button><button className="btn small ghost" onClick={() => { setOpen(false); setRating(0); }}>Cancel</button></div>
        </div>
      )}
    </>
  );
}

/** Lets the user overrule a requirement's status; the job is re-scored server-side and the correction is logged. */
export function StatusCorrection({ target, current, onRescored }: { target: FeedbackTarget; current: string; onRescored: (r: Rescored) => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  return (
    <select aria-label="Correct this status" value="" disabled={busy} title="Wrong? Set the correct status"
      style={{ width: "auto", height: 26, minHeight: 26, fontSize: 12, padding: "0 24px 0 8px" }}
      onClick={(e) => e.stopPropagation()}
      onChange={async (e) => {
        const status = e.target.value;
        if (!status) return;
        setBusy(true);
        try {
          const r = await sendFeedback(target, { rating: -1, correction: { status, was: current } });
          if (r.summary && r.jobs) onRescored({ summary: r.summary, jobs: r.jobs });
          toast(`Marked as ${status}; the score was updated.`, "ok");
        } catch (err) { toast((err as Error).message, "error"); } finally { setBusy(false); }
      }}>
      <option value="">Correct…</option>
      {["met", "partial", "missing"].filter((s) => s !== current).map((s) => <option key={s} value={s}>{s}</option>)}
    </select>
  );
}

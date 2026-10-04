import { Bookmark, ChevronRight, ExternalLink, FileText, Lightbulb, ListChecks, Mail, Maximize2, Mic, PenLine, RotateCcw, ShieldCheck, TrendingUp } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAi } from "../ai";
import { api, post } from "../api";
import type { DeepResult, Gate, JobDetail, ReqCheck, ScoredJob, Summary } from "../types";
import { Feedback, StatusCorrection } from "./Feedback";
import { IconWarn, StatusIcon } from "./Icons";
import { CopyButton, Markdown } from "./Markdown";
import { Modal } from "./Modal";
import { SourceBadges } from "./SourceBadge";
import { relTime } from "./table/JobsTable";
import { useToast } from "./Toast";
import { Alert, Chips, Meter, safeUrl } from "./ui";
import { useStream } from "./useStream";

const TOOLS = [
  ["cover_letter", "Cover letter", Mail], ["resume_bullets", "Bullet ideas", PenLine],
  ["interview_prep", "Interview prep notes", Lightbulb], ["gap_plan", "30-day gap plan", TrendingUp],
] as const;
type Rescored = { summary: Summary; jobs: ScoredJob[] };

export function useJobDetail(analysisId: string, jobId: string) {
  const [detail, setDetail] = useState<JobDetail | null>(null);
  useEffect(() => { api<JobDetail>(`/api/analysis/${analysisId}/job/${jobId}`).then(setDetail).catch(() => {}); }, [analysisId, jobId]);
  return detail;
}

export function jobStatusText(job: ScoredJob, threshold: number) {
  return job.score < threshold ? "Below your bar" : job.gates_failed?.length ? "Fails a hard requirement" : "Qualified";
}

/** Everything about one job except the posting text. Used by the quick-view sheet and the full job page. */
export function JobInsights({ analysisId, job, threshold, onDeep, onRescored, onPick }: {
  analysisId: string; job: ScoredJob; threshold: number; onDeep: (id: string) => Promise<DeepResult>;
  onRescored: (r: Rescored) => void; onPick: (reqId: string) => void;
}) {
  const ai = useAi();
  const toast = useToast();
  const [active, setActive] = useState<string>("");
  const s = useStream();
  const [deepBusy, setDeepBusy] = useState(false);
  const [deepErr, setDeepErr] = useState("");
  async function runDeep() {
    if (!ai.usable) return ai.openModal(true);
    setDeepBusy(true); setDeepErr("");
    try { await onDeep(job.id); } catch (e) { setDeepErr((e as Error).message); } finally { setDeepBusy(false); }
  }
  const d = job.deep;
  const prefMissing = job.missing_skills.filter((x) => !job.required_missing.includes(x));
  const run = (kind: string) => {
    if (!ai.usable) return ai.openModal(true);
    setActive(kind);
    void s.run(`/api/analysis/${analysisId}/tool`, { job_id: job.id, kind }, ai.headers);
  };
  const tone = job.score >= threshold ? "hi" : job.score >= threshold - 15 ? "mid" : "lo";

  return (
    <>
      <div className="drawer-grid">
        <div className="score-big"><span className={`score ${tone}`}>{job.score}%</span>
          <small>{jobStatusText(job, threshold)}</small>
          {d && <small className="muted">rules only {d.det_score}%</small>}</div>
        <div>
          {([["Skills", job.components.skills], ["Requirements", job.components.requirements], ["Role fit", job.components.role],
             ["Experience", job.components.experience], ["Semantic", job.components.semantic]] as const).map(([k, v]) => (
            <div className="comp" key={k}><span>{k}</span><Meter value={v} /><span>{v}%</span></div>
          ))}
        </div>
      </div>

      <div className="agent-links">
        <Link className="btn small primary" to={`/analysis/${analysisId}/tailor/${job.id}`} data-testid="open-tailor"><PenLine aria-hidden="true" />Tailor my resume</Link>
        <Link className="btn small" to={`/analysis/${analysisId}/interview/${job.id}`}><Mic aria-hidden="true" />Practice interview</Link>
        <button className="btn small" data-testid="save-tracker" onClick={async () => {
          try {
            await post("/api/tracker", { job_id: job.id, analysis_id: analysisId, title: job.title, company: job.company, location: job.location,
              url: job.url, score: job.score, source: job.source });
            toast("Saved to your tracker.", "ok");
          } catch (e) { toast((e as Error).message, "error"); }
        }}><Bookmark aria-hidden="true" />Save</button>
        {job.url && <a className="btn small" href={safeUrl(job.url)} target="_blank" rel="noopener noreferrer"><ExternalLink aria-hidden="true" />Open posting</a>}
      </div>

      {job.gates && job.gates.length > 0 && <Gates gates={job.gates} />}
      {(() => {   // a strict-degree blocker is already shown as a gate
        const b = job.blockers.filter((x) => !(job.gates?.some((g) => g.type === "degree") && /degree/i.test(x)));
        return b.length > 0 && <Alert kind="warn"><IconWarn /> {b.join(" ")}</Alert>;
      })()}
      {job.negated_skills.length > 0 && <small className="muted">Not required by this posting (it says so): {job.negated_skills.join(", ")}</small>}

      <h3 className="sec"><ShieldCheck aria-hidden="true" />Deep AI check {d && <span className={`tag ${d.verdict === "strong" || d.verdict === "possible" ? "q" : "nq"}`}>{d.verdict || "done"}</span>}</h3>
      {!d && <div className="deep-cta"><small className="muted">The AI checks every requirement and must quote your resume as evidence; quotes are verified by the server.</small>
        <button className="btn small primary" onClick={runDeep} disabled={deepBusy}>{deepBusy ? "Checking…" : "Run deep AI check"}</button></div>}
      {deepErr && <Alert>{deepErr}</Alert>}
      {d && <>
        {d.summary && <p>{d.summary}</p>}
        <p className="small muted">{d.verified} of {d.assessed} AI judgements verified · {d.disagreements} disagreement{d.disagreements === 1 ? "" : "s"} with the rules ·
          requirement score {d.requirements_component}% · overall {d.det_score}% → <b>{d.final_score}%</b>
          <Feedback target={{ kind: "job_score", analysisId, jobId: job.id, output: `${d.verdict}: ${d.summary}`, model: d.model }} label="this verdict" /></p>
        {d.unverified_claims > 0 && <Alert kind="warn">{d.unverified_claims} AI claim{d.unverified_claims > 1 ? "s" : ""} had no matching or relevant quote in your resume, so the rules verdict was kept.</Alert>}
        <ul className="reqlist">
          {d.requirements.map((r) => (
            <li key={r.id}>
              <StatusIcon s={r.final_status} />
              <div><b>{r.requirement}</b> <small className="muted">{r.importance === "must" ? "required" : "nice to have"}</small>
                <div className="small verdicts">
                  {r.det_status && <span>Rules: <em className={`v-${r.det_status}`}>{r.det_status}</em></span>}
                  <span>AI: <em className={`v-${r.ai_status.replace(" ", "-")}`}>{r.ai_status}</em>{r.verified ? " ✓ verified" : ""}</span>
                  <span>Counted: <b>{r.source === "ai" ? "AI (verified)" : r.source === "you" ? "your correction" : "rules"}</b></span>
                  {r.disagree && <span className="warn-text">disagree</span>}
                  <Feedback target={{ kind: "deep_requirement", analysisId, jobId: job.id, itemId: r.requirement, output: JSON.stringify({ ai_status: r.ai_status, evidence: r.evidence || r.claimed_evidence, note: r.note }), model: d.model }} label="this judgement" />
                </div>
                {r.note && <div className="muted small">{r.note}</div>}
                {r.evidence && <blockquote className="evidence" title="Verified: found in your resume and relevant">“{r.evidence}”</blockquote>}
                {r.flag && <div className="warn-text small"><IconWarn /> {r.flag}{r.claimed_evidence ? `: “${r.claimed_evidence}”` : ""}</div>}
              </div>
            </li>
          ))}
        </ul>
        <button className="link" onClick={runDeep} disabled={deepBusy}><RotateCcw aria-hidden="true" />{deepBusy ? "Re-checking…" : "Re-run AI check"}</button>
      </>}

      {job.requirements.length > 0 && <>
        <h3 className="sec"><ListChecks aria-hidden="true" />Requirement matrix <small className="muted">({job.requirements_met}/{job.requirements.length} met · click a row to find it in the posting · wrong? correct it)</small></h3>
        <Matrix reqs={job.requirements} onPick={onPick} analysisId={analysisId} jobId={job.id} onRescored={onRescored} />
      </>}
      <Chips label="You have" items={[...job.matched_skills, ...job.matched_keywords]} tone="ok" />
      <Chips label="Required, missing" items={job.required_missing} tone="miss" />
      <Chips label="Preferred, missing" items={prefMissing} tone="pref" />
      <Chips label="Posting keywords you lack" items={job.missing_keywords} tone="miss" />
      {job.required_years != null && <div className="job-sub">Experience asked: {job.required_years}+ years{job.required_years_inferred ? " (inferred from title)" : ""}</div>}
      {job.confidence === "low" && <Alert kind="info">Little or no description text was available, so this score is a rough estimate.</Alert>}

      <h3 className="sec">Write with AI</h3>
      <div className="toggles">
        {TOOLS.map(([k, l, I]) => <button key={k} className={`toggle ${active === k ? "on" : ""}`} disabled={s.busy} onClick={() => run(k)}><I aria-hidden="true" />{l}</button>)}
      </div>
      {!ai.usable && <small className="muted">Add an AI key to generate tailored content. <button className="link" onClick={() => ai.openModal(true)}>Open AI settings</button></small>}
      {s.err && <Alert>{s.err}</Alert>}
      {(s.text || s.busy) && (
        <div className="ai-out">
          <div className="ai-out-bar">
            <small>{s.busy ? "Writing…" : "Done. Review and edit before using."}</small>
            <span className="actions">{s.busy ? <button className="btn small" onClick={s.stop}>Stop</button> : <>
              <Feedback target={{ kind: "tool", analysisId, jobId: job.id, itemId: active, output: s.text }} label="this draft" /><CopyButton text={s.text} /></>}</span>
          </div>
          <Markdown text={s.text || "…"} />
        </div>
      )}
    </>
  );
}

/** Quick view (sheet). `?job=` in the URL; the full page lives at /analysis/:aid/job/:jobId. */
export function JobDrawer({ analysisId, job, threshold, onClose, onDeep, onRescored }: {
  analysisId: string; job: ScoredJob; threshold: number; onClose: () => void; onDeep: (id: string) => Promise<DeepResult>; onRescored: (r: Rescored) => void;
}) {
  const detail = useJobDetail(analysisId, job.id);
  const [showDesc, setShowDesc] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  useEffect(() => {
    if (!flash || !showDesc) return;
    document.getElementById(`pl-${flash}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    const t = setTimeout(() => setFlash(null), 2200);
    return () => clearTimeout(t);
  }, [flash, showDesc, detail]);
  return (
    <Modal title={job.title} onClose={onClose} sheet
      subtitle={<div className="job-sub" style={{ marginTop: 4 }}>{[job.company, job.location, job.salary, relTime(job.posted)].filter(Boolean).join(" · ")} <SourceBadges sources={job.sources} /></div>}
      headActions={<Link className="btn small ghost" to={`/analysis/${analysisId}/job/${job.id}`} title="Open the full page with the posting side by side"><Maximize2 aria-hidden="true" />Full page</Link>}>
      <JobInsights analysisId={analysisId} job={job} threshold={threshold} onDeep={onDeep} onRescored={onRescored}
        onPick={(id) => { setShowDesc(true); setFlash(id); }} />
      <h3 className="sec"><button className="disclosure" onClick={() => setShowDesc(!showDesc)} aria-expanded={showDesc}><ChevronRight aria-hidden="true" /><FileText aria-hidden="true" />Job description</button></h3>
      {showDesc && (detail?.description ? <Posting text={detail.description} reqs={job.requirements} gates={job.gates ?? []} flash={flash} />
        : <pre className="desc">No description available.</pre>)}
    </Modal>
  );
}

const HOW_LABEL: Record<string, string> = {
  "exact skill": "Exact skill", "implied skill": "Implied skill", "related skill": "Related skill (partial)",
  "years check": "Years check", "degree check": "Degree check", "term overlap": "Shared terms", "semantic match": "Similar meaning",
  "not found": "Not found", "your correction": "Your correction",
};

export function Gates({ gates }: { gates: Gate[] }) {
  return (
    <div className="gates" data-testid="gates">
      <h3 className="sec">Hard requirements <small className="muted">(pass / fail / unknown, separate from the score)</small></h3>
      <ul>{gates.map((g, i) => (
        <li key={i} className={`gate-${g.status}`}>
          <span className="gate-pill">{g.status === "pass" ? "✓ pass" : g.status === "fail" ? "✕ fail" : "? unknown"}</span>
          <div><b>{g.label}{g.need ? `: ${g.need}` : ""}</b><div className="small muted">“{g.text}”</div><div className="small">{g.reason}</div></div>
        </li>))}</ul>
    </div>
  );
}

function Matrix({ reqs, onPick, analysisId, jobId, onRescored }: { reqs: ReqCheck[]; onPick: (id: string) => void; analysisId: string; jobId: string; onRescored: (r: Rescored) => void }) {
  const [picked, setPicked] = useState<string | null>(null);
  const pick = (id: string) => { setPicked(id); onPick(id); };
  return (
    <div className="matrix-wrap">
      <table className="matrix">
        <thead><tr><th>Requirement</th><th>Status</th><th>Evidence from your resume</th><th>Decided by</th></tr></thead>
        <tbody>{reqs.map((r) => (
          <tr key={r.id} className={picked === r.id ? "picked" : ""} onClick={() => pick(r.id)} tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter") pick(r.id); }}>
            <td>{r.text} {r.preferred && <small className="muted">(nice to have)</small>}</td>
            <td><span className={`st st-${r.status}`}><StatusIcon s={r.status} /> {r.status}</span></td>
            <td>{r.evidence ? <q>{r.evidence}</q> : <span className="muted">—</span>}
              {r.missing.length > 0 && <div className="small miss-line">missing: {r.missing.join(", ")}</div>}
              {r.via?.map((v) => <div key={v} className="small via">{v}</div>)}</td>
            <td><small>{HOW_LABEL[r.how ?? ""] ?? r.how ?? "Rules"}</small>
              <div style={{ marginTop: 4 }}><StatusCorrection current={r.status} onRescored={onRescored}
                target={{ kind: "requirement", analysisId, jobId, itemId: r.text, output: JSON.stringify({ status: r.status, how: r.how, evidence: r.evidence }) }} /></div></td>
          </tr>))}</tbody>
      </table>
    </div>
  );
}

const norm = (x: string) => x.toLowerCase().replace(/^[\s\-•*·▪◦●]+/, "").replace(/\s+/g, " ").trim();

/** The posting with every judged requirement highlighted by status, and gate sentences marked. */
export function Posting({ text, reqs, gates, flash }: { text: string; reqs: ReqCheck[]; gates: Gate[]; flash: string | null }) {
  const lines = text.split("\n");
  const reqFor = (ln: string) => { const n = norm(ln); return n.length > 2 ? reqs.find((r) => { const t = norm(r.text); return n.includes(t) || (t.includes(n) && n.length > 12); }) : undefined; };
  const gateFor = (ln: string) => { const n = norm(ln); return n.length > 2 ? gates.find((g) => n.includes(norm(g.text)) && g.text.length > 4) : undefined; };
  return (
    <div className="desc posting" data-testid="posting">
      {lines.map((ln, i) => {
        const r = reqFor(ln), g = r ? undefined : gateFor(ln);
        if (r) return <mark key={i} id={`pl-${r.id}`} className={`pl st-${r.status} ${flash === r.id ? "flash" : ""}`}>{ln}{"\n"}</mark>;
        if (g) return <mark key={i} className={`pl gate-${g.status}`}>{ln}{"\n"}</mark>;
        return <span key={i}>{ln}{"\n"}</span>;
      })}
      <div className="legend small"><mark className="pl st-met">met</mark> <mark className="pl st-partial">partial</mark> <mark className="pl st-missing">missing</mark> <mark className="pl gate-fail">hard requirement</mark></div>
    </div>
  );
}

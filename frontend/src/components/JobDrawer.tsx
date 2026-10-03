import { useEffect, useState } from "react";
import { useAi } from "../ai";
import { api } from "../api";
import type { DeepResult, JobDetail, ScoredJob } from "../types";
import { IconShield, IconWarn, StatusIcon } from "./Icons";
import { SourceBadges } from "./SourceBadge";
import { CopyButton, Markdown } from "./Markdown";
import { Modal } from "./Modal";
import { Alert, Chips, Meter, safeUrl } from "./ui";
import { useStream } from "./useStream";

const TOOLS = [
  ["cover_letter", "✉ Cover letter"], ["resume_bullets", "✎ Tailor my resume"],
  ["interview_prep", "? Interview prep"], ["gap_plan", "↗ 30-day gap plan"],
] as const;

export function JobDrawer({ analysisId, job, threshold, onClose, onDeep }: { analysisId: string; job: ScoredJob; threshold: number; onClose: () => void; onDeep: (id: string) => Promise<DeepResult> }) {
  const ai = useAi();
  const [detail, setDetail] = useState<JobDetail | null>(null);
  const [showDesc, setShowDesc] = useState(false);
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

  useEffect(() => { api<JobDetail>(`/api/analysis/${analysisId}/job/${job.id}`).then(setDetail).catch(() => {}); }, [analysisId, job.id]);

  const prefMissing = job.missing_skills.filter((x) => !job.required_missing.includes(x));
  const run = (kind: string) => {
    if (!ai.usable) return ai.openModal(true);
    setActive(kind);
    void s.run(`/api/analysis/${analysisId}/tool`, { job_id: job.id, kind }, ai.headers);
  };

  return (
    <Modal title={job.title} onClose={onClose} wide>
      <div className="job-sub">{[job.company, job.location, job.salary].filter(Boolean).join(" · ")}{job.url && <> · <a href={safeUrl(job.url)} target="_blank" rel="noopener noreferrer">View posting ↗</a></>}</div>
      <div className="badges"><SourceBadges sources={job.sources} /></div>
      <div className="drawer-grid">
        <div className="score-big"><span className={`score ${job.score >= threshold ? "hi" : job.score >= threshold - 20 ? "mid" : "lo"}`}>{job.score}%</span>
          <small>{job.score >= threshold ? "Qualified" : "Below threshold"}</small>
          {d && <small className="muted">rules only {d.det_score}%</small>}</div>
        <div>
          {([["Skills", job.components.skills], ["Requirements", job.components.requirements], ["Role fit", job.components.role],
             ["Experience", job.components.experience], ["Semantic", job.components.semantic]] as const).map(([k, v]) => (
            <div className="comp" key={k}><span>{k}</span><Meter value={v} /><span>{v}%</span></div>
          ))}
        </div>
      </div>
      {job.blockers.length > 0 && <Alert kind="warn"><IconWarn /> {job.blockers.join(" ")}</Alert>}
      {job.negated_skills.length > 0 && <small className="muted">Not required by this posting (it says so): {job.negated_skills.join(", ")}</small>}

      <h3 className="sec"><IconShield /> Deep AI check {d && <span className={`tag ${d.verdict === "strong" || d.verdict === "possible" ? "q" : "nq"}`}>{d.verdict || "done"}</span>}</h3>
      {!d && <div className="deep-cta"><small className="muted">The AI checks every requirement and must quote your resume as evidence; quotes are verified by the server.</small>
        <button className="btn small primary" onClick={runDeep} disabled={deepBusy}>{deepBusy ? "Checking…" : "Run deep AI check"}</button></div>}
      {deepErr && <Alert>{deepErr}</Alert>}
      {d && <>
        {d.summary && <p>{d.summary}</p>}
        <p className="small muted">{d.verified} of {d.assessed} AI judgements verified · {d.disagreements} disagreement{d.disagreements === 1 ? "" : "s"} with the rules ·
          requirement score {d.requirements_component}% · overall {d.det_score}% → <b>{d.final_score}%</b></p>
        {d.unverified_claims > 0 && <Alert kind="warn">{d.unverified_claims} AI claim{d.unverified_claims > 1 ? "s" : ""} had no matching or relevant quote in your resume, so the rules verdict was kept.</Alert>}
        <ul className="reqlist">
          {d.requirements.map((r) => (
            <li key={r.id}>
              <StatusIcon s={r.final_status} />
              <div><b>{r.requirement}</b> <small className="muted">{r.importance === "must" ? "required" : "nice to have"}</small>
                <div className="small verdicts">
                  {r.det_status && <span>Rules: <em className={`v-${r.det_status}`}>{r.det_status}</em></span>}
                  <span>AI: <em className={`v-${r.ai_status.replace(" ", "-")}`}>{r.ai_status}</em>{r.verified ? " ✓ verified" : ""}</span>
                  <span>Counted: <b>{r.source === "ai" ? "AI (verified)" : "rules"}</b></span>
                  {r.disagree && <span className="warn-text">disagree</span>}
                </div>
                {r.note && <div className="muted small">{r.note}</div>}
                {r.evidence && <blockquote className="evidence" title="Verified: found in your resume and relevant">“{r.evidence}”</blockquote>}
                {r.flag && <div className="warn-text small"><IconWarn /> {r.flag}{r.claimed_evidence ? `: “${r.claimed_evidence}”` : ""}</div>}
              </div>
            </li>
          ))}
        </ul>
        <button className="link" onClick={runDeep} disabled={deepBusy}>{deepBusy ? "Re-checking…" : "Re-run AI check"}</button>
      </>}

      {job.requirements.length > 0 && <>
        <h3 className="sec">Requirement checklist <small className="muted">(rules-based: {job.requirements_met}/{job.requirements.length} met)</small></h3>
        <ul className="reqlist">
          {job.requirements.map((r) => (
            <li key={r.id}><StatusIcon s={r.status} /><div>{r.text} {r.preferred && <small className="muted">(nice to have)</small>}
              {r.missing.length > 0 && <div className="small miss-line">missing: {r.missing.join(", ")}</div>}</div></li>
          ))}
        </ul>
      </>}
      <Chips label="You have" items={[...job.matched_skills, ...job.matched_keywords]} tone="ok" />
      <Chips label="Required, missing" items={job.required_missing} tone="miss" />
      <Chips label="Preferred, missing" items={prefMissing} tone="pref" />
      <Chips label="Posting keywords you lack" items={job.missing_keywords} tone="miss" />
      {job.required_years != null && <div className="job-sub">Experience asked: {job.required_years}+ years{job.required_years_inferred ? " (inferred from title)" : ""}</div>}
      {job.confidence === "low" && <Alert kind="info">Little or no description text was available, so this score is a rough estimate.</Alert>}

      <h3 className="sec">AI tools for this job</h3>
      <div className="toggles">
        {TOOLS.map(([k, l]) => <button key={k} className={`toggle ${active === k ? "on" : ""}`} disabled={s.busy} onClick={() => run(k)}>{l}</button>)}
      </div>
      {!ai.usable && <small className="muted">Add an AI key to generate tailored content. <button className="link" onClick={() => ai.openModal(true)}>Open AI settings</button></small>}
      {s.err && <Alert>{s.err}</Alert>}
      {(s.text || s.busy) && (
        <div className="ai-out">
          <div className="ai-out-bar">
            <small>{s.busy ? "Writing…" : "Done. Review and edit before using."}</small>
            <span>{s.busy ? <button className="btn small" onClick={s.stop}>Stop</button> : <CopyButton text={s.text} />}</span>
          </div>
          <Markdown text={s.text || "…"} />
        </div>
      )}

      <h3 className="sec"><button className="link" onClick={() => setShowDesc(!showDesc)} aria-expanded={showDesc}>{showDesc ? "▾" : "▸"} Job description</button></h3>
      {showDesc && <pre className="desc">{detail?.description || "No description available."}</pre>}
    </Modal>
  );
}

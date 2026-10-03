import { useEffect, useState } from "react";
import { useAi } from "../ai";
import { api } from "../api";
import type { JobDetail, ScoredJob } from "../types";
import { CopyButton, Markdown } from "./Markdown";
import { Modal } from "./Modal";
import { Alert, Chips, Meter, safeUrl } from "./ui";
import { useStream } from "./useStream";

const TOOLS = [
  ["cover_letter", "✉ Cover letter"], ["resume_bullets", "✎ Tailor my resume"],
  ["interview_prep", "? Interview prep"], ["gap_plan", "↗ 30-day gap plan"],
] as const;

export function JobDrawer({ analysisId, job, threshold, onClose }: { analysisId: string; job: ScoredJob; threshold: number; onClose: () => void }) {
  const ai = useAi();
  const [detail, setDetail] = useState<JobDetail | null>(null);
  const [showDesc, setShowDesc] = useState(false);
  const [active, setActive] = useState<string>("");
  const s = useStream();

  useEffect(() => { api<JobDetail>(`/api/analysis/${analysisId}/job/${job.id}`).then(setDetail).catch(() => {}); }, [analysisId, job.id]);

  const prefMissing = job.missing_skills.filter((x) => !job.required_missing.includes(x));
  const run = (kind: string) => {
    if (!ai.usable) return ai.openModal(true);
    setActive(kind);
    void s.run(`/api/analysis/${analysisId}/tool`, { job_id: job.id, kind }, ai.headers);
  };

  return (
    <Modal title={job.title} onClose={onClose} wide>
      <div className="job-sub">{[job.company, job.location].filter(Boolean).join(" · ")} · <a href={safeUrl(job.url)} target="_blank" rel="noopener noreferrer">View on LinkedIn ↗</a></div>
      <div className="drawer-grid">
        <div className="score-big"><span className={`score ${job.score >= threshold ? "hi" : job.score >= threshold - 20 ? "mid" : "lo"}`}>{job.score}%</span>
          <small>{job.score >= threshold ? "Qualified" : "Below threshold"}</small></div>
        <div>
          {([["Skills", job.components.skills], ["Role fit", job.components.role], ["Experience", job.components.experience]] as const).map(([k, v]) => (
            <div className="comp" key={k}><span>{k}</span><Meter value={v} /><span>{v}%</span></div>
          ))}
        </div>
      </div>
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

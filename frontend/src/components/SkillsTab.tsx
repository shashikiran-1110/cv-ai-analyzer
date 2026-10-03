import type { Analysis } from "../types";
import { SkillPicker } from "./SkillPicker";
import { Alert, Chip, Meter } from "./ui";

export function SkillsTab({ a, extra, setExtra, busy, unlocked, err }: {
  a: Analysis; extra: string[]; setExtra: (v: string[]) => void; busy: boolean; unlocked: number | null; err: string;
}) {
  const s = a.summary;
  const toggle = (skill: string) => setExtra(extra.includes(skill) ? extra.filter((x) => x !== skill) : [...extra, skill]);
  const gaps = s.skill_gaps;
  const maxJobs = Math.max(1, ...gaps.map((g) => g.jobs));
  return (
    <div className="cols">
      <div className="card">
        <h2>What if I had…</h2>
        <p className="muted">Add skills you have or plan to learn. Matches are re-scored instantly so you can see which skills unlock the most jobs.</p>
        <SkillPicker value={extra} onChange={setExtra} />
        {unlocked !== null && extra.length > 0 && (
          <Alert kind={unlocked > 0 ? "ok" : "info"}>
            {busy ? "Re-scoring…" : unlocked > 0 ? `With ${extra.length === 1 ? "this skill" : "these skills"} you'd qualify for ${unlocked} more job${unlocked === 1 ? "" : "s"} than before.` : "These skills don't change how many jobs you qualify for yet, but they still raise match scores."}
          </Alert>
        )}
        {err && <Alert>{err}</Alert>}
        {a.unknown_skills.length > 0 && <small className="warn-text">Ignored (not in the skill list): {a.unknown_skills.join(", ")}</small>}
        <h3 className="sec">Skills you have that these jobs want</h3>
        {s.skill_strengths.length === 0 ? <p className="muted">None detected yet.</p> : s.skill_strengths.map((g) => (
          <div className="learn-item" key={g.skill}>
            <div className="learn-head"><span>{g.skill} <small>{g.category}</small></span><small>{g.jobs} of {s.job_count} postings</small></div>
            <Meter value={g.pct} tone="good" />
          </div>
        ))}
        {s.unused_skills.length > 0 && <>
          <h3 className="sec">On your resume but not asked for</h3>
          <div className="chips">{s.unused_skills.map((x) => <Chip key={x}>{x}</Chip>)}</div>
        </>}
      </div>
      <div className="card">
        <h2>Skill gaps</h2>
        <p className="muted">Missing from your resume, ranked by how many postings want them. Tick “I have this” to test the impact.</p>
        {gaps.length === 0 ? <p className="empty">No recurring skill gaps found.</p> : gaps.map((g) => (
          <div className="learn-item" key={g.skill}>
            <div className="learn-head">
              <span>{g.skill} <small>{g.category}</small></span>
              <label className="check small"><input type="checkbox" checked={extra.includes(g.skill)} onChange={() => toggle(g.skill)} /> I have this</label>
            </div>
            <Meter value={(g.jobs / maxJobs) * 100} tone="warn" />
            <small>{g.jobs} of {s.job_count} postings ({g.pct}%)</small>
          </div>
        ))}
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { post } from "../api";
import { useAi } from "../ai";
import type { SearchParams } from "../types";
import { useSetup } from "../state/setup";
import { ResumeCard, resumeReady } from "./ResumeCard";
import { parsePasted, sourcesPayload, sourcesProblem, SourcesPicker } from "./SourcesPicker";

const TIME = [["24h", "24 hours"], ["week", "Week"], ["month", "Month"], ["any", "Any"], ["custom", "Custom"]] as const;
const EXPERIENCE = [["internship", "Internship"], ["entry", "Entry"], ["associate", "Associate"], ["mid_senior", "Mid-Senior"], ["director", "Director"], ["executive", "Executive"]];
const TYPES = [["full_time", "Full-time"], ["part_time", "Part-time"], ["contract", "Contract"], ["temporary", "Temporary"], ["internship", "Internship"]];
const WORKPLACE = [["on_site", "On-site"], ["hybrid", "Hybrid"], ["remote", "Remote"]];

function MultiChips({ label, options, value, onChange }: { label: string; options: string[][]; value: string[]; onChange: (v: string[]) => void }) {
  return (
    <div className="field">
      <span>{label} <small>(any)</small></span>
      <div className="toggles" role="group" aria-label={label}>
        {options.map(([v, l]) => (
          <button key={v} type="button" className={`toggle ${value.includes(v) ? "on" : ""}`} aria-pressed={value.includes(v)}
            onClick={() => onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v])}>{l}</button>
        ))}
      </div>
    </div>
  );
}

export function SetupStep({ openDiagnose }: { openDiagnose: () => void }) {
  const ai = useAi();
  const navigate = useNavigate();
  const { resume, setResume, params: p, setParams, sources, setSources, opts, setOpts } = useSetup();
  const props = { setResume, setSources, setOpts, openDiagnose };
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [moreFilters, setMoreFilters] = useState(false);
  const max = ai.config?.max_jobs ?? 100;
  const upd = (patch: Partial<SearchParams>) => setParams({ ...p, ...patch });
  // a validation/run error is stale once the user changes what it was about
  useEffect(() => { if (!busy) setErr(""); }, [resume.preview, p.title, sources]);  // eslint-disable-line react-hooks/exhaustive-deps

  const titleNeeded = sources.mode === "portals";
  const problem = !resumeReady(resume) ? "Add your resume first (step 1)."
    : titleNeeded && p.title.trim().length < 2 ? "Enter the job title you're looking for (step 2)."
    : titleNeeded && !(p.count >= 1 && p.count <= max) ? `Number of posts must be 1–${max}.`
    : titleNeeded && p.time_range === "custom" && !(opts.hours >= 1 && opts.hours <= 2160) ? "Custom hours must be 1–2160."
    : sourcesProblem(sources);

  async function run() {
    if (problem) { setErr(problem); return; }
    setErr(""); setBusy(true);
    try {
      let searchId: string;
      if (sources.mode === "paste") {
        ({ search_id: searchId } = await post<{ search_id: string }>("/api/search/manual", { title: p.title.trim() || "Pasted jobs", jobs: parsePasted(sources.paste) }));
      } else if (sources.mode === "sample") {
        ({ search_id: searchId } = await post<{ search_id: string }>("/api/search/sample", { title: p.title.trim() }));
      } else {
        const body = { ...p, title: p.title.trim(), location: p.location.trim(), count: Math.round(p.count),
          ...(p.time_range === "custom" ? { custom_hours: Math.round(opts.hours) } : {}), ...sourcesPayload(sources) };
        ({ search_id: searchId } = await post<{ search_id: string }>("/api/search", body));
      }
      navigate(`/search/${searchId}${opts.review ? "" : "?auto=1"}`);
    } catch (e) { setErr((e as Error).message); setBusy(false); }
  }

  return (
    <section aria-labelledby="h-setup">
      <div className="hero-intro">
        <h1 id="h-setup">See how many real openings you qualify for</h1>
        <p className="lead">Upload your CV, describe the role, pick where to search. We collect postings from LinkedIn, job boards and company career sites, score your resume against every requirement, and show exactly what to improve.</p>
      </div>
      <div className="setup-grid">
        <ResumeCard value={resume} onChange={setResume} />
        <div className="card setup-card">
          <div className="card-head"><span className="num">2</span><div><h2>The role</h2><small>{sources.mode === "portals" ? "What to search for" : "Optional for pasted/sample jobs"}</small></div></div>
          <label className="field"><span>Job title {titleNeeded && <b className="req">*</b>}</span>
            <input value={p.title} onChange={(e) => upd({ title: e.target.value })} maxLength={100} placeholder="e.g. Data Engineer" autoComplete="off" />
          </label>
          <label className="field"><span>Location</span>
            <input value={p.location} onChange={(e) => upd({ location: e.target.value })} maxLength={100} placeholder="e.g. London · Remote · blank = anywhere" autoComplete="off" />
          </label>
          <div className="field"><span>Number of posts</span>
            <div className="count-row">
              <input type="range" min={5} max={max} step={5} value={Math.max(5, Math.min(max, p.count || 5))} aria-label="Number of posts slider" onChange={(e) => upd({ count: +e.target.value })} />
              <input type="number" min={1} max={max} value={p.count || ""} aria-label="Number of posts" onChange={(e) => upd({ count: +e.target.value })} />
            </div>
          </div>
          <div className="field"><span>Posted within</span>
            <div className="seg" role="radiogroup" aria-label="Time range">
              {TIME.map(([v, l]) => <button key={v} type="button" role="radio" aria-checked={p.time_range === v} onClick={() => upd({ time_range: v })}>{l}</button>)}
            </div>
            {p.time_range === "custom" && <div className="custom-row"><input type="number" min={1} max={2160} value={opts.hours} onChange={(e) => props.setOpts({ ...opts, hours: +e.target.value })} aria-label="Custom hours" /> <span>hours</span></div>}
          </div>
          {sources.mode === "portals" && (
            <label className="check"><input type="checkbox" checked={p.strict} onChange={(e) => upd({ strict: e.target.checked })} />
              <span>Only jobs whose title matches the role <small>(recommended: keeps the qualify % honest)</small></span></label>
          )}
          <button type="button" className="link" onClick={() => setMoreFilters(!moreFilters)} aria-expanded={moreFilters}>
            {moreFilters ? "▾" : "▸"} More filters{p.experience.length + p.job_types.length + p.workplace.length ? ` (${p.experience.length + p.job_types.length + p.workplace.length} set)` : ""}
          </button>
          {moreFilters && <>
            <MultiChips label="Experience level" options={EXPERIENCE} value={p.experience} onChange={(v) => upd({ experience: v })} />
            <MultiChips label="Job type" options={TYPES} value={p.job_types} onChange={(v) => upd({ job_types: v })} />
            <MultiChips label="Workplace" options={WORKPLACE} value={p.workplace} onChange={(v) => upd({ workplace: v })} />
            <div className="field"><span>Sort</span>
              <div className="seg" role="radiogroup" aria-label="Sort">
                {[["recent", "Most recent"], ["relevant", "Most relevant"]].map(([v, l]) => <button key={v} type="button" role="radio" aria-checked={p.sort === v} onClick={() => upd({ sort: v })}>{l}</button>)}
              </div>
            </div>
          </>}
        </div>
      </div>

      <SourcesPicker value={sources} onChange={props.setSources} />

      <div className="card run-card">
        <div className="opts-row">
          <label className="field grow"><span>Count a job as “qualified” at <b>{opts.threshold}%</b>+</span>
            <input type="range" min={30} max={90} step={5} value={opts.threshold} onChange={(e) => props.setOpts({ ...opts, threshold: +e.target.value })} />
          </label>
          <div className="opt-checks">
            <label className="check"><input type="checkbox" checked={opts.wantAi && ai.usable} disabled={!ai.usable} onChange={(e) => props.setOpts({ ...opts, wantAi: e.target.checked })} />
              <span>AI-written advice {ai.usable ? <small>(sends resume text to your AI provider)</small> : <button type="button" className="link" onClick={() => ai.openModal(true)}>add a key</button>}</span></label>
            <label className="check"><input type="checkbox" checked={opts.review} onChange={(e) => props.setOpts({ ...opts, review: e.target.checked })} /><span>Let me review the jobs before analyzing</span></label>
          </div>
        </div>
        <div className="run-row">
          <small className="muted">{problem || "Ready."}</small>
          <button className="btn primary big" onClick={run} disabled={busy} data-testid="run">{busy ? "Starting…" : opts.review ? "Find jobs" : "Find jobs & analyze"}</button>
        </div>
      </div>

      {err && (
        <div className="alert error" role="alert">
          <div>{err}</div>
          <div className="actions small-gap">
            <button className="btn small" onClick={props.openDiagnose}>Run connection check</button>
            {sources.mode === "portals" && <button className="btn small" onClick={() => props.setSources({ ...sources, mode: "paste" })}>Paste jobs instead</button>}
            {sources.mode !== "sample" && <button className="btn small" onClick={() => props.setSources({ ...sources, mode: "sample" })}>Try sample jobs</button>}
          </div>
        </div>
      )}
      <p className="fine">Sources are queried from this app's server through their public pages/APIs. Some (LinkedIn, Wellfound) limit automated access, so results vary; keep volumes modest and respect each site's terms.</p>
    </section>
  );
}

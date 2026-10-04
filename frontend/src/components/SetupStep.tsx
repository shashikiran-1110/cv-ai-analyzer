import { ChevronRight, CircleCheck, Circle, Play } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { post } from "../api";
import { useAi } from "../ai";
import type { SearchParams } from "../types";
import { useSetup } from "../state/setup";
import { PlanCard } from "./PlanCard";
import { ResumeCard, resumeReady } from "./ResumeCard";
import { useSavedLinks } from "./SavedLinks";
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
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [moreFilters, setMoreFilters] = useState(false);
  const max = ai.config?.max_jobs ?? 500;
  const saved = (useSavedLinks().data ?? []).map((l) => l.url);
  const upd = (patch: Partial<SearchParams>) => setParams({ ...p, ...patch });
  // a validation/run error is stale once the user changes what it was about
  useEffect(() => { if (!busy) setErr(""); }, [resume.preview, p.title, sources]);  // eslint-disable-line react-hooks/exhaustive-deps

  const titleNeeded = sources.mode === "portals";
  const problem = !resumeReady(resume) ? "Add your resume first."
    : titleNeeded && p.title.trim().length < 2 ? "Enter the job title you're looking for."
    : titleNeeded && !(p.count >= 1 && p.count <= max) ? `Number of posts must be 1–${max}.`
    : titleNeeded && p.time_range === "custom" && !(opts.hours >= 1 && opts.hours <= 2160) ? "Custom hours must be 1–2160."
    : sourcesProblem(sources, saved);

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
          ...(p.time_range === "custom" ? { custom_hours: Math.round(opts.hours) } : {}), ...sourcesPayload(sources, saved) };
        ({ search_id: searchId } = await post<{ search_id: string }>("/api/search", body));
      }
      navigate(`/search/${searchId}${opts.review ? "" : "?auto=1"}`);
    } catch (e) { setErr((e as Error).message); setBusy(false); }
  }

  const nFilters = p.experience.length + p.job_types.length + p.workplace.length;
  const pasted = sources.mode === "paste" ? parsePasted(sources.paste).length : 0;
  const checks: { ok: boolean; label: string; detail: string }[] = [
    { ok: resumeReady(resume), label: "Resume", detail: resume.preview ? `${resume.preview.words} words · ${resume.preview.skills.length} skills` : "Upload a PDF or paste text" },
    { ok: !titleNeeded || p.title.trim().length >= 2, label: "Role", detail: p.title.trim() ? `${p.title.trim()}${p.location.trim() ? ` · ${p.location.trim()}` : ""}` : titleNeeded ? "Enter a job title" : "Optional" },
    { ok: !sourcesProblem(sources, saved), label: "Sources",
      detail: sources.mode === "portals" ? `${sources.selected.length} selected · up to ${p.count} posts` : sources.mode === "paste" ? `${pasted} pasted job${pasted === 1 ? "" : "s"}` : "14 sample postings" },
    { ok: ai.usable, label: "AI (optional)", detail: ai.usable ? (ai.settings.key ? `${ai.settings.provider === "openai" ? "OpenAI" : "Anthropic"} key set` : "Server key") : "Rules-only analysis" },
  ];

  return (
    <section aria-labelledby="h-setup">
      <div className="hero-intro">
        <div className="eyebrow">New search</div>
        <h1 id="h-setup">See how many real openings you qualify for</h1>
        <p className="lead">Upload your CV, describe the role and pick where to search. Every posting is scored against your resume requirement by requirement, with the evidence shown.</p>
      </div>
      <div className="setup-layout">
        <div className="setup-main">
          <div className="setup-grid">
            <ResumeCard value={resume} onChange={setResume} />
            <div className="card setup-card">
              <div className="card-head"><span className={`num ${checks[1].ok && p.title.trim() ? "done" : ""}`}>2</span><div><h2>The role</h2><small>{sources.mode === "portals" ? "What to search for" : "Optional for pasted or sample jobs"}</small></div></div>
              <label className="field"><span>Job title {titleNeeded && <b className="req">*</b>}</span>
                <input value={p.title} onChange={(e) => upd({ title: e.target.value })} maxLength={100} placeholder="e.g. Data Engineer" autoComplete="off" />
              </label>
              {sources.mode === "portals" && <PlanCard params={p} onApply={(x) => upd(x)} />}
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
                {p.time_range === "custom" && <div className="custom-row"><input type="number" min={1} max={2160} value={opts.hours} onChange={(e) => setOpts({ ...opts, hours: +e.target.value })} aria-label="Custom hours" /> <span>hours</span></div>}
              </div>
              {sources.mode === "portals" && (
                <label className="check"><input type="checkbox" checked={p.strict} onChange={(e) => upd({ strict: e.target.checked })} />
                  <span>Only jobs whose title matches the role <small>(recommended: keeps the qualify % honest)</small></span></label>
              )}
              <button type="button" className="disclosure" onClick={() => setMoreFilters(!moreFilters)} aria-expanded={moreFilters}>
                <ChevronRight aria-hidden="true" />More filters{nFilters ? ` (${nFilters} set)` : ""}
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
          <SourcesPicker value={sources} onChange={setSources} />
          <p className="fine">Sources are queried from this app's server through their public pages and APIs. Some (LinkedIn, Wellfound) limit automated access, so results vary; keep volumes modest and respect each site's terms.</p>
        </div>

        <aside className="setup-aside" aria-label="Run">
          <div className="card ready run-card">
            <h2>Ready to run</h2>
            <ul>
              {checks.map((c) => (
                <li key={c.label}>{c.ok ? <CircleCheck className="ok" aria-label="done" /> : <Circle className="todo" aria-label="to do" />}
                  <div><span>{c.label}</span><small>{c.detail}</small></div></li>
              ))}
            </ul>
            <button className="btn primary big" onClick={run} disabled={busy} data-testid="run"><Play aria-hidden="true" />{busy ? "Starting…" : opts.review ? "Find jobs" : "Find jobs & analyze"}</button>
            <p className="problem">{problem || "Everything's set."}</p>
            <div className="ready-opts">
              <div className="thr"><div className="thr-head"><span>Count a job as qualified at</span><b>{opts.threshold}%+</b></div>
                <input type="range" min={30} max={90} step={5} value={opts.threshold} aria-label="Qualification threshold" onChange={(e) => setOpts({ ...opts, threshold: +e.target.value })} /></div>
              <label className="check"><input type="checkbox" checked={opts.wantAi && ai.usable} disabled={!ai.usable} onChange={(e) => setOpts({ ...opts, wantAi: e.target.checked })} />
                <span>AI-written advice {ai.usable ? <small>(sends resume text to your AI provider)</small> : <button type="button" className="link" onClick={() => ai.openModal(true)}>add a key</button>}</span></label>
              <label className="check"><input type="checkbox" checked={opts.review} onChange={(e) => setOpts({ ...opts, review: e.target.checked })} /><span>Let me review the jobs before analyzing</span></label>
              <label className="field" style={{ fontWeight: 400 }}><span>Deep-check my top jobs with AI <small>(verified, quote by quote)</small></span>
                <select value={ai.usable && opts.wantAi ? opts.autoDeep : 0} disabled={!ai.usable || !opts.wantAi} aria-label="Auto deep-check"
                  onChange={(e) => setOpts({ ...opts, autoDeep: +e.target.value })}>
                  <option value={0}>Off (run it from the report)</option><option value={5}>Top 5</option><option value={10}>Top 10</option><option value={25}>Top 25</option>
                </select>
                {opts.autoDeep > 0 && ai.usable && opts.wantAi && <small>Skipped automatically if the estimate is above the cost cap; you'll see the estimate in the report.</small>}</label>
            </div>
          </div>
          {err && (
            <div className="alert error" role="alert">
              <div>{err}</div>
              <div className="actions small-gap">
                <button className="btn small" onClick={openDiagnose}>Run connection check</button>
                {sources.mode === "portals" && <button className="btn small" onClick={() => setSources({ ...sources, mode: "paste" })}>Paste jobs instead</button>}
                {sources.mode !== "sample" && <button className="btn small" onClick={() => setSources({ ...sources, mode: "sample" })}>Try sample jobs</button>}
              </div>
            </div>
          )}
        </aside>
      </div>
    </section>
  );
}

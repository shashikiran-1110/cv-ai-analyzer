import { useEffect, useMemo, useRef, useState } from "react";
import { post } from "../api";
import { useAi } from "../ai";
import type { Analysis, ScoredJob } from "../types";
import { AssistantTab } from "./AssistantTab";
import { JobDrawer } from "./JobDrawer";
import { SkillsTab } from "./SkillsTab";
import { Alert, Gauge, Meter, safeUrl, scoreTone } from "./ui";
import { Markdown } from "./Markdown";

type Tab = "overview" | "jobs" | "skills" | "assistant";
const TABS: [Tab, string][] = [["overview", "Overview"], ["jobs", "Jobs"], ["skills", "Skills & what-if"], ["assistant", "AI assistant"]];
const BUCKETS = ["0–19", "20–39", "40–59", "60–79", "80+"];

export function ReportStep({ initial, initialThreshold, onRestart, onResume }: {
  initial: Analysis; initialThreshold: number; onRestart: () => void; onResume: () => void;
}) {
  const ai = useAi();
  const [a, setA] = useState<Analysis>(initial);
  const [tab, setTab] = useState<Tab>("overview");
  const [threshold, setThreshold] = useState(initialThreshold);
  const [extra, setExtraState] = useState<string[]>(initial.extra_skills);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState<ScoredJob | null>(null);
  const baseline = useRef(new Map(initial.jobs.map((j) => [j.id, j.score])));
  const timer = useRef<number>(0);
  const seq = useRef(0);

  const qualifying = useMemo(() => a.jobs.filter((j) => j.score >= threshold).length, [a.jobs, threshold]);
  const baseQual = useMemo(() => [...baseline.current.values()].filter((s) => s >= threshold).length, [threshold]);
  const dist = useMemo(() => { const d = [0, 0, 0, 0, 0]; a.jobs.forEach((j) => d[Math.min(4, Math.floor(j.score / 20))]++); return d; }, [a.jobs]);
  const n = a.jobs.length, pct = n ? Math.round((qualifying / n) * 100) : 0;

  // Debounced server re-score whenever the user's extra skills change.
  function setExtra(next: string[]) {
    setExtraState(next); setErr("");
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(async () => {
      const id = ++seq.current;
      setBusy(true);
      try {
        const r = await post<Pick<Analysis, "extra_skills" | "unknown_skills" | "summary" | "jobs" | "insights">>(
          `/api/analysis/${a.analysis_id}/rescore`, { extra_skills: next, threshold });
        if (id !== seq.current) return;
        setA((prev) => ({ ...prev, ...r, insights: prev.insights.source === "local" ? r.insights : prev.insights }));
      } catch (e) { if (id === seq.current) setErr((e as Error).message); }
      finally { if (id === seq.current) setBusy(false); }
    }, 350);
  }
  useEffect(() => () => window.clearTimeout(timer.current), []);

  return (
    <section aria-labelledby="h-report">
      <div className="head-row">
        <div><h1 id="h-report">Your match report</h1>
          <p className="lead">{n} postings for “{a.query.title}”{a.query.location ? ` in ${a.query.location}` : ""}</p></div>
        <div className="actions">
          <button className="btn" onClick={onResume}>Try another resume</button>
          <button className="btn" onClick={onRestart}>New search</button>
          <button className="btn" onClick={() => exportCsv(a, threshold)}>CSV</button>
          <button className="btn" onClick={() => exportJson(a, threshold)}>JSON</button>
          <button className="btn" onClick={() => window.print()}>Print</button>
        </div>
      </div>

      <div className="tabs" role="tablist">
        {TABS.map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>)}
      </div>

      {tab === "overview" && <Overview a={a} extra={extra} threshold={threshold} setThreshold={setThreshold} qualifying={qualifying} pct={pct} dist={dist}
        delta={extra.length ? qualifying - baseQual : 0} onTab={setTab} />}
      {tab === "jobs" && <JobsTab jobs={a.jobs} threshold={threshold} onOpen={setOpen} />}
      {tab === "skills" && <SkillsTab a={a} extra={extra} setExtra={setExtra} busy={busy} err={err} unlocked={qualifying - baseQual} />}
      {tab === "assistant" && <AssistantTab analysisId={a.analysis_id} jobs={a.jobs} />}
      {open && <JobDrawer analysisId={a.analysis_id} job={open} threshold={threshold} onClose={() => setOpen(null)} />}
      {!ai.usable && tab === "overview" && !a.insights.ai_error && a.insights.source === "local" && (
        <Alert kind="info">Showing built-in analysis. <button className="link" onClick={() => ai.openModal(true)}>Add an AI key</button> for personalised advice, a chat assistant, cover letters and interview prep.</Alert>
      )}
    </section>
  );
}

function Overview({ a, extra, threshold, setThreshold, qualifying, pct, dist, delta, onTab }: {
  a: Analysis; extra: string[]; threshold: number; setThreshold: (n: number) => void; qualifying: number; pct: number; dist: number[]; delta: number; onTab: (t: Tab) => void;
}) {
  const ins = a.insights, s = a.summary, n = a.jobs.length;
  const learn = ins.skills_to_learn.filter((x) => !extra.some((e) => e.toLowerCase() === x.skill.toLowerCase()));
  const max = Math.max(1, ...dist);
  return (
    <>
      <div className="hero card">
        <Gauge pct={pct} label={`You qualify for ${qualifying} of ${n} jobs (${pct}%)`} />
        <div className="hero-txt">
          <div className="big">{qualifying} of {n} jobs {delta !== 0 && <span className={`delta ${delta > 0 ? "up" : "down"}`}>{delta > 0 ? "+" : ""}{delta} with your extra skills</span>}</div>
          <div className="sub">you'd qualify for at <b>{threshold}%</b>+ match</div>
          <input type="range" min={30} max={90} step={5} value={threshold} onChange={(e) => setThreshold(+e.target.value)} aria-label="Qualification threshold" />
          <div className="stats">
            <div><span><b>{s.avg_score}</b>%</span><small>average match</small></div>
            <div><span><b>{a.jobs[0]?.score ?? 0}</b>%</span><small>best match</small></div>
            <div><span><b>{s.resume_years || "?"}</b></span><small>yrs experience found</small></div>
          </div>
        </div>
        <div className="dist" aria-label="Score distribution">
          {dist.map((c, i) => <div key={i}><b>{c}</b><i style={{ height: `${Math.max(3, Math.round((c / max) * 70))}px` }} />{BUCKETS[i]}</div>)}
        </div>
      </div>

      {ins.ai_error && <Alert kind="warn">{ins.ai_error}</Alert>}
      {ins.summary && <div className="card summary"><b>Overall: </b>{ins.summary}{ins.source !== "local" && <div className="fine">Advice written by {ins.source === "openai" ? "OpenAI" : "Anthropic"} from your resume and the posting analysis.</div>}</div>}

      <div className="cols">
        <div className="card"><h2><span className="dot good" />Strengths</h2>
          <ul className="bullets">{(ins.strengths.length ? ins.strengths : ["Nothing stands out yet."]).map((t, i) => <li key={i}><Markdown text={t} /></li>)}</ul></div>
        <div className="card"><h2><span className="dot warn" />Areas to improve</h2>
          <ul className="bullets">{(ins.improvements.length ? ins.improvements : ["No major issues detected."]).map((t, i) => <li key={i}><Markdown text={t} /></li>)}</ul></div>
      </div>

      <div className="card">
        <h2>Skills to work on</h2>
        <p className="muted">Ranked by how many postings ask for it and your resume doesn't show it. <button className="link" onClick={() => onTab("skills")}>Try “what if I learned…” →</button></p>
        {learn.length === 0 ? <div className="empty">No recurring skill gaps found. Nice.</div> : (() => {
          const m = Math.max(1, ...learn.map((x) => x.jobs || 0));
          return learn.map((x, i) => (
            <div className="learn-item" key={x.skill}>
              <div className="learn-head"><span>{i + 1}. {x.skill}</span>{x.jobs != null && <small>{x.jobs} of {n} postings</small>}</div>
              {x.jobs != null && <Meter value={((x.jobs || 0) / m) * 100} tone="warn" />}
              {x.why && <p>{x.why}</p>}{x.how && <p><b>How: </b>{x.how}</p>}
            </div>
          ));
        })()}
      </div>
    </>
  );
}

function JobsTab({ jobs, threshold, onOpen }: { jobs: ScoredJob[]; threshold: number; onOpen: (j: ScoredJob) => void }) {
  const [only, setOnly] = useState(false);
  const [sort, setSort] = useState("score");
  const [q, setQ] = useState("");
  const rows = useMemo(() => {
    const f = q.trim().toLowerCase();
    const r = jobs.filter((j) => (!only || j.score >= threshold) && (!f || `${j.title} ${j.company} ${j.location}`.toLowerCase().includes(f)));
    r.sort(sort === "score-asc" ? (x, y) => x.score - y.score : sort === "company" ? (x, y) => x.company.localeCompare(y.company) : (x, y) => y.score - x.score);
    return r;
  }, [jobs, only, sort, q, threshold]);
  return (
    <div className="card">
      <div className="toolbar">
        <input type="search" placeholder="Search jobs…" aria-label="Search jobs" value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="check"><input type="checkbox" checked={only} onChange={(e) => setOnly(e.target.checked)} /> Qualified only</label>
        <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort">
          <option value="score">Best match</option><option value="score-asc">Weakest match</option><option value="company">Company</option>
        </select>
      </div>
      <p className="muted">{rows.length} of {jobs.length} shown. Click a job for details, missing skills and AI tools (cover letter, resume tailoring, interview prep).</p>
      <ul className="results">
        {rows.length === 0 && <li className="empty">No jobs match.</li>}
        {rows.map((j) => (
          <li key={j.id}>
            <button className="r-head" onClick={() => onOpen(j)}>
              <span className={`score ${scoreTone(j.score, threshold)}`}>{j.score}%</span>
              <span>
                <div className="job-title">{j.title}<span className={`tag ${j.score >= threshold ? "q" : "nq"}`}>{j.score >= threshold ? "Qualified" : "Below"}</span>
                  {j.confidence === "low" && <span className="pill">rough</span>}</div>
                <div className="job-sub">{[j.company, j.location].filter(Boolean).join(" · ")}</div>
                {j.required_missing.length > 0 && <div className="job-sub miss-line">Missing: {j.required_missing.slice(0, 5).join(", ")}{j.required_missing.length > 5 ? "…" : ""}</div>}
              </span>
              <span className="chev" aria-hidden="true">›</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function download(name: string, mime: string, body: string) {
  const url = URL.createObjectURL(new Blob([body], { type: mime }));
  const el = document.createElement("a"); el.href = url; el.download = name; document.body.append(el); el.click(); el.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function exportCsv(a: Analysis, t: number) {
  const esc = (v: unknown) => { let s = String(v ?? ""); if (/^[=+\-@]/.test(s)) s = "'" + s; return `"${s.replace(/"/g, '""')}"`; };
  const rows = [["Title", "Company", "Location", "Match %", "Qualified", "Missing required skills", "Missing preferred skills", "URL"],
    ...a.jobs.map((j) => [j.title, j.company, j.location, j.score, j.score >= t ? "yes" : "no", j.required_missing.join("; "),
      j.missing_skills.filter((s) => !j.required_missing.includes(s)).join("; "), safeUrl(j.url)])];
  download("cv-match-report.csv", "text/csv", rows.map((r) => r.map(esc).join(",")).join("\n"));
}
function exportJson(a: Analysis, t: number) {
  download("cv-match-report.json", "application/json", JSON.stringify({ threshold: t, query: a.query, summary: a.summary, insights: a.insights, jobs: a.jobs }, null, 2));
}

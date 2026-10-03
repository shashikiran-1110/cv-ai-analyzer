import { useEffect, useMemo, useRef, useState } from "react";
import { post } from "../api";
import { useAi } from "../ai";
import type { Analysis, DeepResult, ScoredJob } from "../types";
import { AssistantTab } from "./AssistantTab";
import { IconShield, IconWarn } from "./Icons";
import { JobDrawer } from "./JobDrawer";
import { Markdown } from "./Markdown";
import { SkillsTab } from "./SkillsTab";
import { SourceBadges, sourceName } from "./SourceBadge";
import { Alert, Gauge, Meter, safeUrl, scoreTone } from "./ui";

type Tab = "overview" | "jobs" | "skills" | "assistant";
const TABS: [Tab, string][] = [["overview", "Overview"], ["jobs", "Jobs"], ["skills", "Skills & what-if"], ["assistant", "AI assistant"]];
const BUCKETS = ["0–19", "20–39", "40–59", "60–79", "80+"];
type Partial_ = Pick<Analysis, "summary" | "jobs">;

export function ReportStep({ initial, initialThreshold, notes = [], onRestart }: { initial: Analysis; initialThreshold: number; notes?: string[]; onRestart: () => void }) {
  const ai = useAi();
  const [a, setA] = useState<Analysis>(initial);
  const [tab, setTab] = useState<Tab>("overview");
  const [threshold, setThreshold] = useState(initialThreshold);
  const [extra, setExtraState] = useState<string[]>(initial.extra_skills);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [deep, setDeep] = useState<{ running: boolean; done: number; total: number; errors: string[] }>({ running: false, done: 0, total: 0, errors: [] });
  const stopDeep = useRef(false);
  const baseline = useRef(new Map(initial.jobs.map((j) => [j.id, j.score])));
  const timer = useRef<number>(0);
  const seq = useRef(0);

  const qualifying = useMemo(() => a.jobs.filter((j) => j.score >= threshold).length, [a.jobs, threshold]);
  const baseQual = useMemo(() => [...baseline.current.values()].filter((s) => s >= threshold).length, [threshold]);
  const dist = useMemo(() => { const d = [0, 0, 0, 0, 0]; a.jobs.forEach((j) => d[Math.min(4, Math.floor(j.score / 20))]++); return d; }, [a.jobs]);
  const verified = a.jobs.filter((j) => j.deep).length;
  const n = a.jobs.length, pct = n ? Math.round((qualifying / n) * 100) : 0;
  const merge = (r: Partial_) => setA((prev) => ({ ...prev, ...r }));

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
  useEffect(() => () => { window.clearTimeout(timer.current); stopDeep.current = true; }, []);

  async function deepOne(jobId: string): Promise<DeepResult> {
    const r = await post<Partial_ & { deep: DeepResult }>(`/api/analysis/${a.analysis_id}/deep/${jobId}`, {}, ai.headers);
    merge({ summary: r.summary, jobs: r.jobs });
    return r.deep;
  }

  async function deepTop(count: number) {
    if (!ai.usable) return ai.openModal(true);
    const ids = [...a.jobs].sort((x, y) => y.score - x.score).filter((j) => !j.deep).slice(0, count).map((j) => j.id);
    if (!ids.length) return;
    stopDeep.current = false;
    setDeep({ running: true, done: 0, total: ids.length, errors: [] });
    const queue = [...ids];
    const worker = async () => {
      while (queue.length && !stopDeep.current) {
        const id = queue.shift()!;
        try { await deepOne(id); }
        catch (e) {
          const msg = (e as Error).message;
          setDeep((d) => ({ ...d, errors: [...d.errors, msg] }));
          if (/key|quota|rate limit|reach the AI/i.test(msg)) stopDeep.current = true;  // systemic: don't hammer
        }
        setDeep((d) => ({ ...d, done: d.done + 1 }));
      }
    };
    await Promise.all([worker(), worker()]);
    setDeep((d) => ({ ...d, running: false }));
  }

  const openJob = a.jobs.find((j) => j.id === open) ?? null;
  return (
    <section aria-labelledby="h-report">
      <div className="head-row">
        <div><h1 id="h-report">Your match report</h1>
          <p className="lead">{n} postings for “{a.query.title}”{a.query.location ? ` in ${a.query.location}` : ""} · {Object.entries(a.summary.by_source).map(([k, v]) => `${sourceName(k)} ${v}`).join(" · ")}</p></div>
        <div className="actions">
          <button className="btn" onClick={onRestart}>← Change setup</button>
          <button className="btn" onClick={() => exportCsv(a, threshold)}>CSV</button>
          <button className="btn" onClick={() => exportJson(a, threshold)}>JSON</button>
          <button className="btn" onClick={() => window.print()}>Print</button>
        </div>
      </div>

      {notes.length > 0 && (
        <details className="notes"><summary>{notes.length} source note{notes.length > 1 ? "s" : ""} (some sources were blocked or partial)</summary>
          <ul>{notes.map((x, i) => <li key={i}>{x}</li>)}</ul></details>
      )}
      <div className="tabs" role="tablist">
        {TABS.map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>)}
      </div>

      {tab === "overview" && <Overview a={a} extra={extra} threshold={threshold} setThreshold={setThreshold} qualifying={qualifying} pct={pct} dist={dist}
        delta={extra.length ? qualifying - baseQual : 0} verified={verified} onTab={setTab} />}
      {tab === "jobs" && <>
        <div className="card deep-card">
          <div><b><IconShield /> Deep AI check</b> <small className="muted">The AI checks each requirement against your resume and must quote evidence; the server verifies every quote. Scores become 50% deterministic + 50% AI. {verified ? `${verified} job${verified > 1 ? "s" : ""} verified.` : ""}</small></div>
          <div className="actions">
            {deep.running ? <>
              <span className="muted">Verifying {deep.done}/{deep.total}…</span>
              <button className="btn small" onClick={() => { stopDeep.current = true; }}>Stop</button>
            </> : [5, 10, 20].map((k) => <button key={k} className="btn small" onClick={() => deepTop(k)}>Verify top {k}</button>)}
          </div>
          {!ai.usable && <small className="muted">Needs an AI key. <button className="link" onClick={() => ai.openModal(true)}>Add one</button></small>}
          {deep.errors.length > 0 && <Alert kind="warn">{deep.errors.length} check{deep.errors.length > 1 ? "s" : ""} failed: {[...new Set(deep.errors)].join(" | ")}</Alert>}
        </div>
        <JobsTab jobs={a.jobs} threshold={threshold} onOpen={(j) => setOpen(j.id)} />
      </>}
      {tab === "skills" && <SkillsTab a={a} extra={extra} setExtra={setExtra} busy={busy} err={err} unlocked={qualifying - baseQual} />}
      {tab === "assistant" && <AssistantTab analysisId={a.analysis_id} jobs={a.jobs} />}
      {openJob && <JobDrawer analysisId={a.analysis_id} job={openJob} threshold={threshold} onClose={() => setOpen(null)} onDeep={deepOne} />}
      {!ai.usable && tab === "overview" && a.insights.source === "local" && !a.insights.ai_error && (
        <Alert kind="info">Showing built-in analysis. <button className="link" onClick={() => ai.openModal(true)}>Add an AI key</button> for personalised advice, deep requirement checks, chat, cover letters and interview prep.</Alert>
      )}
    </section>
  );
}

function Overview({ a, extra, threshold, setThreshold, qualifying, pct, dist, delta, verified, onTab }: {
  a: Analysis; extra: string[]; threshold: number; setThreshold: (n: number) => void; qualifying: number; pct: number; dist: number[];
  delta: number; verified: number; onTab: (t: Tab) => void;
}) {
  const ins = a.insights, s = a.summary, n = a.jobs.length;
  const learn = ins.skills_to_learn.filter((x) => !extra.some((e) => e.toLowerCase() === x.skill.toLowerCase()));
  const max = Math.max(1, ...dist);
  return (
    <>
      <div className="hero card">
        <Gauge pct={pct} label={`You qualify for ${qualifying} of ${n} jobs (${pct}%)`} />
        <div className="hero-txt">
          <div className="big" data-testid="qualify">{qualifying} of {n} jobs {delta !== 0 && <span className={`delta ${delta > 0 ? "up" : "down"}`}>{delta > 0 ? "+" : ""}{delta} with your extra skills</span>}</div>
          <div className="sub">you'd qualify for at <b>{threshold}%</b>+ match{verified ? ` · ${verified} AI-verified` : ""}</div>
          <input type="range" min={30} max={90} step={5} value={threshold} onChange={(e) => setThreshold(+e.target.value)} aria-label="Qualification threshold" />
          <div className="stats">
            <div><span><b>{s.avg_score}</b>%</span><small>average match</small></div>
            <div><span><b>{a.jobs[0]?.score ?? 0}</b>%</span><small>best match</small></div>
            <div><span><b>{s.resume_years || "?"}</b></span><small>yrs experience</small></div>
            <div><span><b>{s.resume_skills.length}</b></span><small>skills detected</small></div>
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

      {s.common_blockers.length > 0 && (
        <div className="card">
          <h2><IconWarn /> Common blockers</h2>
          <p className="muted">Hard requirements in these postings that your resume doesn't show.</p>
          <ul className="bullets">{s.common_blockers.map((b) => <li key={b.text}>{b.text} <small className="muted">({b.jobs} job{b.jobs > 1 ? "s" : ""})</small></li>)}</ul>
        </div>
      )}

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
      <p className="muted">{rows.length} of {jobs.length} shown. Click a job for its requirement checklist, deep AI check and tools (cover letter, resume tailoring, interview prep).</p>
      <ul className="results">
        {rows.length === 0 && <li className="empty">No jobs match.</li>}
        {rows.map((j) => (
          <li key={j.id}>
            <button className="r-head" onClick={() => onOpen(j)}>
              <span className={`score ${scoreTone(j.score, threshold)}`}>{j.score}%</span>
              <span className="r-main">
                <span className="job-title">{j.title}<span className={`tag ${j.score >= threshold ? "q" : "nq"}`}>{j.score >= threshold ? "Qualified" : "Below"}</span>
                  {j.deep && <span className="tag ai" title={`AI ${j.deep.ai_score}% · rules ${j.deep.det_score}%`}>AI-verified</span>}
                  {j.confidence === "low" && <span className="pill">rough</span>}</span>
                <span className="job-sub">{[j.company, j.location, j.salary].filter(Boolean).join(" · ")}</span>
                <span className="job-sub">
                  {j.requirements.length > 0 && <>Requirements met {j.requirements_met}/{j.requirements.length} · </>}
                  {j.blockers.length > 0 && <span className="miss-line"><IconWarn /> {j.blockers[0]} · </span>}
                  <SourceBadges sources={j.sources} />
                </span>
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
  const rows = [["Title", "Company", "Location", "Match %", "Rules %", "AI %", "Qualified", "Requirements met", "Missing required skills", "Blockers", "Sources", "URL"],
    ...a.jobs.map((j) => [j.title, j.company, j.location, j.score, j.score_det ?? j.score, j.deep?.ai_score ?? "", j.score >= t ? "yes" : "no",
      `${j.requirements_met}/${j.requirements.length}`, j.required_missing.join("; "), j.blockers.join("; "), j.sources.join("; "), safeUrl(j.url)])];
  download("cv-match-report.csv", "text/csv", rows.map((r) => r.map(esc).join(",")).join("\n"));
}
function exportJson(a: Analysis, t: number) {
  download("cv-match-report.json", "application/json", JSON.stringify({ threshold: t, query: a.query, summary: a.summary, insights: a.insights, jobs: a.jobs }, null, 2));
}

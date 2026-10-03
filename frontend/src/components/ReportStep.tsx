import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, post } from "../api";
import { CountUp } from "../hooks/useCountUp";
import { useRunEvents } from "../hooks/useRunEvents";
import { useToast } from "./Toast";
import { useAi } from "../ai";
import type { Analysis, DeepEstimate, DeepResult, ScoredJob, Spend } from "../types";
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
/** Qualifies = score at/above the threshold and no failed gate (ROADMAP §6.3); gates never change the score. */
const qualifies = (j: Pick<ScoredJob, "score" | "gates_failed">, t: number) => j.score >= t && !(j.gates_failed?.length);

export function ReportStep({ initial, notes = [] }: { initial: Analysis; notes?: string[] }) {
  const ai = useAi();
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const onRestart = () => navigate("/");
  const [params, setParams] = useSearchParams();
  const [a, setAState] = useState<Analysis>(initial);
  // URL holds the view state so refresh, back/forward and shared links restore it (ROADMAP §9.1)
  const tab = (["overview", "jobs", "skills", "assistant"].includes(params.get("tab") || "") ? params.get("tab") : "overview") as Tab;
  const threshold = Math.max(30, Math.min(90, Number(params.get("t")) || initial.summary.threshold || 60));
  const open = params.get("job");
  const setParam = (k: string, v: string | null) => setParams((p) => { const n = new URLSearchParams(p); if (v === null) n.delete(k); else n.set(k, v); return n; }, { replace: k === "t" });
  const setTab = (t: Tab) => setParam("tab", t === "overview" ? null : t);
  const setThreshold = (t: number) => setParam("t", String(t));
  const setOpen = (id: string | null) => setParam("job", id);
  const setA = (u: Analysis | ((p: Analysis) => Analysis)) => setAState((prev) => {
    const next = typeof u === "function" ? (u as (p: Analysis) => Analysis)(prev) : u;
    qc.setQueryData(["analysis", next.analysis_id], next);
    return next;
  });

  // AI advice arrives after the deterministic results (ROADMAP §3.5)
  useRunEvents(a.insights.pending ? a.insights_run_id : null, (e) => {
    if (e.type === "insight.ready") { setA((p) => ({ ...p, insights: e.data.insights, insights_run_id: null })); toast("AI advice is ready.", "ok"); }
    if (e.type === "run.finished" && e.data.status === "error") setA((p) => ({ ...p, insights: { ...p.insights, pending: false, ai_error: "AI advice failed." } }));
  }, () => { void api<Analysis>(`/api/analysis/${a.analysis_id}`).then((x) => setA({ ...x, insights: { ...x.insights, pending: false } })); });
  const [extra, setExtraState] = useState<string[]>(initial.extra_skills);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [deep, setDeep] = useState<{ running: boolean; done: number; total: number; errors: string[] }>({ running: false, done: 0, total: 0, errors: [] });
  const stopDeep = useRef(false);
  const baseline = useRef(new Map(initial.jobs.map((j) => [j.id, { score: j.score, gates_failed: j.gates_failed }])));
  const timer = useRef<number>(0);
  const seq = useRef(0);

  const qualifying = useMemo(() => a.jobs.filter((j) => qualifies(j, threshold)).length, [a.jobs, threshold]);
  const baseQual = useMemo(() => [...baseline.current.values()].filter((j) => qualifies(j, threshold)).length, [threshold]);
  const gated = useMemo(() => {
    const by: Record<string, number> = {};
    const hit = a.jobs.filter((j) => j.score >= threshold && j.gates_failed?.length);
    hit.forEach((j) => new Set(j.gates_failed).forEach((g) => { by[g] = (by[g] || 0) + 1; }));
    return { count: hit.length, by };
  }, [a.jobs, threshold]);
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
  // back from the profile page with saved corrections: re-score once with them
  useEffect(() => {
    if (params.get("rescore")) { setParam("rescore", null); setExtra(extra); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // AI spend so far + a pre-flight estimate for "Verify top N" (ROADMAP §8.2)
  const [spend, setSpend] = useState<Spend | null>(null);
  const [est, setEst] = useState<Record<number, DeepEstimate>>({});
  const [extracting, setExtracting] = useState(false);
  const refreshSpend = () => { void api<Spend>(`/api/analysis/${a.analysis_id}/costs`).then(setSpend).catch(() => {}); };
  useEffect(() => {
    if (tab !== "jobs") return;
    refreshSpend();
    if (!ai.usable) return;
    for (const k of [5, 10, 20]) void api<DeepEstimate>(`/api/analysis/${a.analysis_id}/deep-estimate?n=${k}`, { headers: ai.headers })
      .then((e) => setEst((p) => ({ ...p, [k]: e }))).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, ai.usable, verified]);
  const usd = (x: number) => (x < 0.01 ? "<$0.01" : `$${x.toFixed(2)}`);

  async function extractTop(count: number) {
    if (!ai.usable) return ai.openModal(true);
    const ids = [...a.jobs].sort((x, y) => y.score - x.score).slice(0, count).map((j) => j.id);
    setExtracting(true);
    try {
      const r = await post<Partial_ & { extracted: number; using_ai_requirements: number }>(`/api/analysis/${a.analysis_id}/extract`, { job_ids: ids }, ai.headers);
      merge({ summary: r.summary, jobs: r.jobs });
      toast(`AI requirement lists in use for ${r.using_ai_requirements} of ${ids.length} jobs (every item checked against the posting text).`, "ok");
    } catch (e) { toast((e as Error).message, "error"); }
    finally { setExtracting(false); refreshSpend(); }
  }

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
    // parallel checks can answer out of order; the server's copy has every verified job
    try { const fresh = await api<Analysis>(`/api/analysis/${a.analysis_id}`); merge({ summary: fresh.summary, jobs: fresh.jobs }); } catch { /* keep what we have */ }
    setDeep((d) => ({ ...d, running: false }));
    refreshSpend();
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
        delta={extra.length ? qualifying - baseQual : 0} verified={verified} onTab={setTab} gated={gated} />}
      {tab === "jobs" && <>
        <div className="card deep-card">
          <div><b><IconShield /> Deep AI check</b> <small className="muted">The AI re-judges each job's requirement checklist and must quote your resume; the server checks every quote exists and is relevant. Only verified AI judgements change a requirement, then the normal scoring formula is re-applied. {verified ? `${verified} job${verified > 1 ? "s" : ""} checked.` : ""}</small></div>
          <div className="actions">
            {deep.running ? <>
              <span className="muted">Verifying {deep.done}/{deep.total}…</span>
              <button className="btn small" onClick={() => { stopDeep.current = true; }}>Stop</button>
            </> : <>{[5, 10, 20].map((k) => <button key={k} className="btn small" onClick={() => deepTop(k)}
                title={est[k]?.estimate_usd != null ? `About ${usd(est[k].estimate_usd!)} for ${est[k].calls} job(s) with ${est[k].model}` : est[k]?.message || ""}>
                Verify top {k}{est[k]?.estimate_usd != null && est[k].calls > 0 ? <small className="est"> ≈{usd(est[k].estimate_usd!)}</small> : null}</button>)}
              <button className="btn small ghost" disabled={extracting} onClick={() => extractTop(10)}
                title="The AI splits each posting into clean, typed requirements; any item it can't point to in the posting is discarded.">
                {extracting ? "Reading postings…" : "AI requirement lists (top 10)"}</button></>}
          </div>
          {spend && spend.calls > 0 && <div className="cost-line" data-testid="ai-spend">AI used for this analysis: <b>{spend.calls}</b> call{spend.calls > 1 ? "s" : ""}
            {spend.cost_known ? <> · <b>{usd(spend.cost_usd)}</b></> : " · cost unknown for this model"}
            {spend.cached_tokens > 0 && <> · {Math.round(spend.cached_tokens / 1000)}k tokens from prompt cache</>}
            {spend.result_cache_hits > 0 && <> · {spend.result_cache_hits} answer{spend.result_cache_hits > 1 ? "s" : ""} reused</>}</div>}
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

function Overview({ a, extra, threshold, setThreshold, qualifying, pct, dist, delta, verified, onTab, gated }: {
  a: Analysis; extra: string[]; threshold: number; setThreshold: (n: number) => void; qualifying: number; pct: number; dist: number[];
  delta: number; verified: number; onTab: (t: Tab) => void; gated: { count: number; by: Record<string, number> };
}) {
  const ins = a.insights, s = a.summary, n = a.jobs.length;
  const learn = ins.skills_to_learn.filter((x) => !extra.some((e) => e.toLowerCase() === x.skill.toLowerCase()));
  const max = Math.max(1, ...dist);
  return (
    <>
      <div className="hero card">
        <Gauge pct={pct} label={`You qualify for ${qualifying} of ${n} jobs (${pct}%)`} />
        <div className="hero-txt">
          <div className="big" data-testid="qualify" data-value={`${qualifying}/${n}`}><CountUp value={qualifying} /> of {n} jobs {delta !== 0 && <span className={`delta ${delta > 0 ? "up" : "down"}`}>{delta > 0 ? "+" : ""}{delta} with your extra skills</span>}</div>
          <div className="sub">you'd qualify for at <b>{threshold}%</b>+ match with no failed hard requirement{verified ? ` · ${verified} AI-verified` : ""}</div>
          {gated.count > 0 && <div className="gate-note" data-testid="gated"><b>{gated.count}</b> more score {threshold}%+ but fail a hard requirement:{" "}
            {Object.entries(gated.by).sort((x, y) => y[1] - x[1]).map(([g, c]) => `${g} ×${c}`).join(", ")}.{" "}
            {a.resume_id && <Link to={`/profile/${a.resume_id}?from=${encodeURIComponent(`/analysis/${a.analysis_id}?rescore=1`)}#eligibility`}>Wrong? Set your eligibility</Link>}</div>}
          <input type="range" min={30} max={90} step={5} value={threshold} onChange={(e) => setThreshold(+e.target.value)} aria-label="Qualification threshold" />
          <div className="stats">
            <div><span><b><CountUp value={s.avg_score} /></b>%</span><small>average match</small></div>
            <div><span><b><CountUp value={a.jobs[0]?.score ?? 0} /></b>%</span><small>best match</small></div>
            <div><span><b>{s.resume_years ? s.resume_years.toFixed(1) : "?"}</b></span><small>yrs experience</small></div>
            <div><span><b>{s.resume_skills.length}</b></span><small>skills detected</small></div>
          </div>
          {a.resume_id && <Link className="link small" to={`/profile/${a.resume_id}?from=${encodeURIComponent(`/analysis/${a.analysis_id}?rescore=1`)}`}>Years or skills wrong? Review what was read from your resume →</Link>}
        </div>
        <div className="dist" aria-label="Score distribution">
          {dist.map((c, i) => <div key={i}><b>{c}</b><i style={{ height: `${Math.max(3, Math.round((c / max) * 70))}px` }} />{BUCKETS[i]}</div>)}
        </div>
      </div>

      {(ins as { pending?: boolean }).pending && <div className="card summary shimmer" aria-live="polite"><b>AI advice is being written…</b> <small className="muted">Your scores are final; personalised advice will appear here in a moment.</small></div>}
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
    const r = jobs.filter((j) => (!only || qualifies(j, threshold)) && (!f || `${j.title} ${j.company} ${j.location}`.toLowerCase().includes(f)));
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
                <span className="job-title">{j.title}<span className={`tag ${qualifies(j, threshold) ? "q" : "nq"}`}>{qualifies(j, threshold) ? "Qualified" : j.score >= threshold ? "Gate" : "Below"}</span>
                  {j.gates_failed?.map((g) => <span key={g} className="tag gate" title={j.gates?.find((x) => x.label === g)?.reason}>✕ {g}</span>)}
                  {j.deep && <span className="tag ai" title={`Rules ${j.deep.det_score}% → ${j.deep.final_score}% with ${j.deep.verified} verified AI judgement(s)`}>AI-verified</span>}
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
  const rows = [["Title", "Company", "Location", "Match %", "Rules-only %", "AI verified reqs", "Qualified", "Requirements met", "Missing required skills", "Blockers", "Sources", "URL"],
    ...a.jobs.map((j) => [j.title, j.company, j.location, j.score, j.score_det ?? j.score, j.deep ? `${j.deep.verified}/${j.deep.assessed}` : "", qualifies(j, t) ? "yes" : "no",
      `${j.requirements_met}/${j.requirements.length}`, j.required_missing.join("; "), j.blockers.join("; "), j.sources.join("; "), safeUrl(j.url)])];
  download("cv-match-report.csv", "text/csv", rows.map((r) => r.map(esc).join(",")).join("\n"));
}
function exportJson(a: Analysis, t: number) {
  download("cv-match-report.json", "application/json", JSON.stringify({ threshold: t, query: a.query, summary: a.summary, insights: a.insights, jobs: a.jobs }, null, 2));
}

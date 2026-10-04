import { useQueryClient } from "@tanstack/react-query";
import { Bell, Braces, Briefcase, Download, FileText, MapPin, Plus, Printer, ShieldCheck, Sparkles, Square } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, post } from "../api";
import { useAi } from "../ai";
import { useRunEvents } from "../hooks/useRunEvents";
import type { Analysis, DeepEstimate, DeepResult, ScoredJob, Spend } from "../types";
import { AssistantTab } from "./AssistantTab";
import { HBars, ScoreHistogram } from "./charts";
import { Feedback } from "./Feedback";
import { IconWarn } from "./Icons";
import { JobDrawer } from "./JobDrawer";
import { JobsAnalytics } from "./JobsAnalytics";
import { AutoDeepBanner, CareerReport, StrategyCard } from "./AiReport";
import { Markdown } from "./Markdown";
import { useRegisterCommands } from "./shell/ShellProvider";
import { SkillsTab } from "./SkillsTab";
import { sourceName } from "./SourceBadge";
import { JobsTable, qualifies } from "./table/JobsTable";
import { useToast } from "./Toast";
import { Alert, Meter, safeUrl } from "./ui";

type Tab = "overview" | "jobs" | "skills" | "assistant";
const TAB_IDS: Tab[] = ["overview", "jobs", "skills", "assistant"];
type Partial_ = Pick<Analysis, "summary" | "jobs">;

export function ReportStep({ initial, notes = [] }: { initial: Analysis; notes?: string[] }) {
  const ai = useAi();
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [a, setAState] = useState<Analysis>(initial);
  // URL holds the view state so refresh, back/forward and shared links restore it (ROADMAP §9.1)
  const tab = (TAB_IDS.includes(params.get("tab") as Tab) ? params.get("tab") : "overview") as Tab;
  const threshold = Math.max(30, Math.min(90, Number(params.get("t")) || initial.summary.threshold || 60));
  const open = params.get("job");
  const setParam = (k: string, v: string | null) => setParams((p) => { const n = new URLSearchParams(p); if (v === null) n.delete(k); else n.set(k, v); return n; }, { replace: k === "t" });
  const setTab = (t: Tab) => setParam("tab", t === "overview" ? null : t);
  const setThreshold = (t: number) => setParam("t", String(t));
  const setOpen = useCallback((id: string | null) => setParams((p) => { const n = new URLSearchParams(p); if (id === null) n.delete("job"); else n.set("job", id); return n; }), [setParams]);
  const setA = (u: Analysis | ((p: Analysis) => Analysis)) => setAState((prev) => {
    const next = typeof u === "function" ? (u as (p: Analysis) => Analysis)(prev) : u;
    qc.setQueryData(["analysis", next.analysis_id], next);
    return next;
  });

  // AI advice arrives after the deterministic results (ROADMAP §3.5)
  // one background run streams: AI advice → apply strategy → auto deep-checks (each step independently)
  const refetch = () => api<Analysis>(`/api/analysis/${a.analysis_id}`).then((x) => setA((p) => ({ ...p, ...x })));
  useRunEvents(a.insights_run_id ?? null, (e) => {
    if (e.type === "insight.ready") { setA((p) => ({ ...p, insights: e.data.insights })); toast("AI advice is ready.", "ok"); }
    if (e.type === "strategy.ready") setA((p) => ({ ...p, strategy: e.data.strategy }));
    if (e.type === "deep.progress" || e.type === "deep.skipped") setA((p) => ({ ...p, auto_deep: e.data }));
    if (e.type === "deep.done") { void refetch(); toast(`AI verified your top ${e.data.total} jobs.`, "ok"); }
    if (e.type === "run.finished") {
      if (e.data.status === "error") setA((p) => ({ ...p, insights: { ...p.insights, pending: false, ai_error: p.insights.ai_error || "AI advice failed." } }));
      void refetch().then(() => setA((p) => ({ ...p, insights_run_id: null })));
    }
  }, () => { void refetch().then(() => setA((p) => ({ ...p, insights: { ...p.insights, pending: false }, insights_run_id: null }))); });
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
  const verified = a.jobs.filter((j) => j.deep).length;
  const n = a.jobs.length;
  const merge = useCallback((r: Partial_) => setA((prev) => ({ ...prev, ...r })), []);  // eslint-disable-line react-hooks/exhaustive-deps

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
  const perCall = est[5]?.estimate_usd != null && est[5].calls ? est[5].estimate_usd / est[5].calls : null;

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

  async function deepIds(ids: string[]) {
    if (!ai.usable) return ai.openModal(true);
    if (!ids.length || deep.running) return;
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
  const deepTop = (count: number) => deepIds([...a.jobs].sort((x, y) => y.score - x.score).filter((j) => !j.deep).slice(0, count).map((j) => j.id));

  async function saveJobs(jobs: ScoredJob[]) {
    let ok = 0;
    for (const job of jobs) {
      try {
        await post("/api/tracker", { job_id: job.id, analysis_id: a.analysis_id, title: job.title, company: job.company, location: job.location, url: job.url, score: job.score, source: job.source });
        ok++;
      } catch (e) { toast((e as Error).message, "error"); }
    }
    if (ok) toast(`Saved ${ok} job${ok > 1 ? "s" : ""} to Applications.`, "ok");
  }
  async function watch() {
    try { await post(`/api/watches`, { analysis_id: a.analysis_id, threshold, frequency: "daily" }); toast("Watching this search: new matches will appear under Watches.", "ok"); }
    catch (e) { toast((e as Error).message, "error"); }
  }

  const sorted = useMemo(() => [...a.jobs].sort((x, y) => y.score - x.score), [a.jobs]);
  useRegisterCommands("report", [
    { id: "tab-overview", group: "This report", label: "Show overview", run: () => setTab("overview") },
    { id: "tab-jobs", group: "This report", label: "Show jobs table", run: () => setTab("jobs") },
    { id: "tab-skills", group: "This report", label: "Skills & what-if", run: () => setTab("skills") },
    { id: "tab-assistant", group: "This report", label: "Ask the AI assistant", run: () => setTab("assistant") },
    { id: "verify10", group: "This report", label: "Deep-verify top 10 jobs", icon: <ShieldCheck />, disabled: deep.running,
      hint: est[10]?.estimate_usd != null ? `≈${usd(est[10].estimate_usd!)}` : undefined, run: () => { setTab("jobs"); void deepTop(10); } },
    { id: "export-csv", group: "This report", label: "Export CSV", icon: <Download />, run: () => exportCsv(threshold, a.jobs) },
    { id: "watch", group: "This report", label: "Watch this search", icon: <Bell />, run: () => void watch() },
    ...sorted.slice(0, 60).map((j) => ({
      id: `job-${j.id}`, group: "Jobs in this report", label: `${j.title}${j.company ? ` · ${j.company}` : ""}`,
      keywords: [j.company, j.location], icon: <Briefcase />, right: <span className={`score small ${j.score >= threshold ? "hi" : j.score >= threshold - 15 ? "mid" : "lo"}`}>{j.score}%</span>,
      run: () => navigate(`/analysis/${a.analysis_id}/job/${j.id}`),
    })),
  ]);

  const openJob = a.jobs.find((j) => j.id === open) ?? null;
  const onOpenJob = useCallback((j: ScoredJob) => setOpen(j.id), [setOpen]);
  const srcLine = Object.entries(a.summary.by_source).map(([k, v]) => `${sourceName(k)} ${v}`).join(" · ");
  return (
    <section aria-labelledby="h-report">
      <div className="page-head report-head">
        <div>
          <div className="eyebrow">Match report</div>
          <h1 id="h-report">{a.query.title || "Your match report"}</h1>
          <div className="report-meta">
            {a.query.location && <span><MapPin aria-hidden="true" />{a.query.location}</span>}
            <span><FileText aria-hidden="true" />{n} postings</span>
            {srcLine && <span>{srcLine}</span>}
          </div>
        </div>
        <div className="actions">
          <Link className="btn" to="/"><Plus aria-hidden="true" />New search</Link>
          <button className="btn" data-testid="watch-search" onClick={watch}><Bell aria-hidden="true" />Watch this search</button>
          <ExportMenu onCsv={() => exportCsv(threshold, a.jobs)} onJson={() => exportJson(a, threshold)} />
        </div>
      </div>

      {notes.length > 0 && (
        <details className="notes"><summary>{notes.length} source note{notes.length > 1 ? "s" : ""} (some sources were blocked or partial)</summary>
          <ul>{notes.map((x, i) => <li key={i}>{x}</li>)}</ul></details>
      )}
      <div className="tabs" role="tablist">
        {([["overview", "Overview"], ["jobs", "Jobs"], ["skills", "Skills & what-if"], ["assistant", "AI assistant"]] as [Tab, string][]).map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>
            {l}{k === "jobs" && <span className="count">{n}</span>}</button>))}
      </div>

      {tab === "overview" && <Overview a={a} extra={extra} threshold={threshold} setThreshold={setThreshold} qualifying={qualifying}
        delta={extra.length ? qualifying - baseQual : 0} verified={verified} onTab={setTab} gated={gated} />}
      {tab === "jobs" && <>
        <AutoDeepBanner a={a} />
        <JobsAnalytics a={a} threshold={threshold} onOpen={onOpenJob} />
        <div className="card deep-card">
          <div className="deep-title"><ShieldCheck aria-hidden="true" /><div><b>Deep AI check</b>
            <div className="muted" style={{ margin: 0 }}>The AI re-judges each job's requirements and must quote your resume; the server checks every quote exists and is relevant. Only verified judgements change a requirement, then the normal formula is re-applied.{verified ? ` ${verified} job${verified > 1 ? "s" : ""} checked.` : ""}</div></div></div>
          <div className="actions">
            {deep.running ? <>
              <span className="spin" aria-hidden="true" /><span className="muted" style={{ margin: 0 }}>Verifying {deep.done}/{deep.total}…</span>
              <button className="btn small" onClick={() => { stopDeep.current = true; }}><Square aria-hidden="true" />Stop</button>
            </> : <>{[5, 10, 20].map((k) => <button key={k} className="btn small" onClick={() => deepTop(k)}
                title={est[k]?.estimate_usd != null ? `About ${usd(est[k].estimate_usd!)} for ${est[k].calls} job(s) with ${est[k].model}` : est[k]?.message || ""}>
                Verify top {k}{est[k]?.estimate_usd != null && est[k].calls > 0 ? <small className="est">≈{usd(est[k].estimate_usd!)}</small> : null}</button>)}
              <button className="btn small ghost" disabled={extracting} onClick={() => extractTop(10)}
                title="The AI splits each posting into clean, typed requirements; any item it can't point to in the posting is discarded.">
                <Sparkles aria-hidden="true" />{extracting ? "Reading postings…" : "AI requirement lists (top 10)"}</button></>}
          </div>
          {spend && spend.calls > 0 && <div className="cost-line" data-testid="ai-spend">AI used for this analysis: <b>{spend.calls}</b> call{spend.calls > 1 ? "s" : ""}
            {spend.cost_known ? <> · <b>{usd(spend.cost_usd)}</b></> : " · cost unknown for this model"}
            {spend.cached_tokens > 0 && <> · {Math.round(spend.cached_tokens / 1000)}k tokens from prompt cache</>}
            {spend.result_cache_hits > 0 && <> · {spend.result_cache_hits} answer{spend.result_cache_hits > 1 ? "s" : ""} reused</>}</div>}
          {!ai.usable && <small className="muted">Needs an AI key. <button className="link" onClick={() => ai.openModal(true)}>Add one</button></small>}
          {deep.errors.length > 0 && <Alert kind="warn">{deep.errors.length} check{deep.errors.length > 1 ? "s" : ""} failed: {[...new Set(deep.errors)].join(" | ")}</Alert>}
        </div>
        <JobsTable jobs={a.jobs} threshold={threshold} onOpen={onOpenJob}
          bulk={{
            verify: (ids) => void deepIds(ids.filter((id) => !a.jobs.find((j) => j.id === id)?.deep)),
            save: (jobs) => void saveJobs(jobs),
            compare: (ids) => navigate(`/analysis/${a.analysis_id}/compare?ids=${ids.join(",")}`),
            exportCsv: (jobs) => exportCsv(threshold, jobs),
            verifyHint: perCall != null ? (k) => `≈${usd(perCall * k)}` : undefined,
          }} />
      </>}
      {tab === "skills" && <SkillsTab a={a} extra={extra} setExtra={setExtra} busy={busy} err={err} unlocked={qualifying - baseQual} />}
      {tab === "assistant" && <AssistantTab analysisId={a.analysis_id} jobs={a.jobs} />}
      {openJob && <JobDrawer analysisId={a.analysis_id} job={openJob} threshold={threshold} onClose={() => setOpen(null)} onDeep={deepOne} onRescored={merge} />}
      {!ai.usable && tab === "overview" && a.insights.source === "local" && !a.insights.ai_error && (
        <Alert kind="info">Showing built-in analysis. <button className="link" onClick={() => ai.openModal(true)}>Add an AI key</button> for personalised advice, deep requirement checks, chat, cover letters and interview prep.</Alert>
      )}
    </section>
  );
}

function ExportMenu({ onCsv, onJson }: { onCsv: () => void; onJson: () => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  return (
    <div className="menu" ref={ref}>
      <button className="btn" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}><Download aria-hidden="true" />Export</button>
      {open && <div className="menu-pop" role="menu">
        <button role="menuitem" onClick={() => { setOpen(false); onCsv(); }}><Download />CSV (all jobs)</button>
        <button role="menuitem" onClick={() => { setOpen(false); onJson(); }}><Braces />JSON</button>
        <button role="menuitem" onClick={() => { setOpen(false); window.print(); }}><Printer />Print / PDF</button>
      </div>}
    </div>
  );
}

function Overview({ a, extra, threshold, setThreshold, qualifying, delta, verified, onTab, gated }: {
  a: Analysis; extra: string[]; threshold: number; setThreshold: (n: number) => void; qualifying: number;
  delta: number; verified: number; onTab: (t: Tab) => void; gated: { count: number; by: Record<string, number> };
}) {
  const ins = a.insights, s = a.summary, n = a.jobs.length;
  const learn = ins.skills_to_learn.filter((x) => !extra.some((e) => e.toLowerCase() === x.skill.toLowerCase()));
  const best = a.jobs.reduce<ScoredJob | null>((m, j) => (!m || j.score > m.score ? j : m), null);
  const pct = n ? Math.round((qualifying / n) * 100) : 0;
  const profileLink = a.resume_id ? `/profile/${a.resume_id}?from=${encodeURIComponent(`/analysis/${a.analysis_id}?rescore=1`)}` : "";
  return (
    <>
      <div className="kpis">
        <div className="kpi">
          <span className="k-label">Qualified at {threshold}%+</span>
          <b data-testid="qualify" data-value={`${qualifying}/${n}`}>{qualifying}<small> of {n} jobs</small>
            {delta !== 0 && <span className={`delta ${delta > 0 ? "up" : "down"}`}>{delta > 0 ? "+" : ""}{delta} with extra skills</span>}</b>
          <div className="k-sub">{pct}% of postings · no failed hard requirement</div>
        </div>
        <div className="kpi"><span className="k-label">Average match</span><b>{s.avg_score}<small>%</small></b><div className="k-sub">across {n} postings</div></div>
        <div className="kpi"><span className="k-label">Best match</span><b>{best?.score ?? 0}<small>%</small></b>
          <div className="k-sub" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{best ? `${best.title}${best.company ? ` · ${best.company}` : ""}` : "—"}</div></div>
        <div className="kpi"><span className="k-label">Your profile</span><b>{s.resume_years ? s.resume_years.toFixed(1) : "?"}<small> yrs</small></b>
          <div className="k-sub">{s.resume_skills.length} skills detected{verified ? ` · ${verified} AI-verified` : ""}</div></div>
      </div>

      <div className="card tight">
        <div className="thr-control" style={{ marginTop: 0 }}>
          <label htmlFor="thr">Count a job as qualified at</label>
          <input id="thr" type="range" min={30} max={90} step={5} value={threshold} onChange={(e) => setThreshold(+e.target.value)} aria-label="Qualification threshold" />
          <b className="num-t">{threshold}%</b>
        </div>
        {gated.count > 0 && <div className="gate-note" data-testid="gated"><b>{gated.count}</b> more score {threshold}%+ but fail a hard requirement:{" "}
          {Object.entries(gated.by).sort((x, y) => y[1] - x[1]).map(([g, c]) => `${g} ×${c}`).join(", ")}.{" "}
          {profileLink && <Link to={`${profileLink}#eligibility`}>Wrong? Set your eligibility</Link>}</div>}
        {profileLink && <Link className="link small" to={profileLink}>Years or skills wrong? Review what was read from your resume →</Link>}
      </div>

      {ins.pending && <div className="card summary shimmer" aria-live="polite"><b>AI advice is being written…</b> <small className="muted">Your scores are final; personalised advice will appear here in a moment.</small></div>}
      {ins.ai_error && <Alert kind="warn">{ins.ai_error}</Alert>}
      {ins.summary && (
        <div className="card summary"><b>Overall: </b>{ins.summary}
          {(ins.unverified_numbers?.length ?? 0) > 0 && <div className="warn-text small" style={{ marginTop: 6 }} data-testid="insights-unverified">
            <IconWarn /> Numbers not found in your analysis: {ins.unverified_numbers!.join(", ")}. Treat them with caution.</div>}
          {ins.source !== "local" && <div className="fine" style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 4 }}>
            Advice written by {ins.source === "openai" ? "OpenAI" : "Anthropic"} from your resume and the posting analysis.
            <Feedback target={{ kind: "insights", analysisId: a.analysis_id, output: [ins.summary, ...ins.strengths, ...ins.improvements].join("\n") }} label="this advice" /></div>}
        </div>
      )}

      <AutoDeepBanner a={a} />
      <StrategyCard a={a} threshold={threshold} />
      <CareerReport a={a} />

      <div className="overview-grid">
        <div className="card"><h2>Score distribution</h2><ScoreHistogram scores={a.jobs.map((j) => j.score)} threshold={threshold} /></div>
        <div className="card"><h2>Most-requested gaps</h2>
          {s.skill_gaps.length ? <HBars rows={s.skill_gaps.slice(0, 7).map((g) => ({ label: g.skill, value: g.jobs, hint: `${g.jobs} of ${n} postings` }))} total={n} tone="warn" />
            : <p className="muted">No recurring skill gaps found.</p>}
          <button className="link small" onClick={() => onTab("skills")}>Try “what if I learned…” →</button>
        </div>
      </div>

      <div className="cols" style={{ marginTop: 16 }}>
        <div className="card"><h2><span className="dot good" />Strengths</h2>
          <ul className="bullets">{(ins.strengths.length ? ins.strengths : ["Nothing stands out yet."]).map((t, i) => <li key={i}><Markdown text={t} /></li>)}</ul></div>
        <div className="card"><h2><span className="dot warn" />Areas to improve</h2>
          <ul className="bullets">{(ins.improvements.length ? ins.improvements : ["No major issues detected."]).map((t, i) => <li key={i}><Markdown text={t} /></li>)}</ul></div>
      </div>

      {s.common_blockers.length > 0 && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2><IconWarn /> Common blockers</h2>
          <p className="muted">Hard requirements in these postings that your resume doesn't show.</p>
          <ul className="bullets">{s.common_blockers.map((b) => <li key={b.text}>{b.text} <small className="muted">({b.jobs} job{b.jobs > 1 ? "s" : ""})</small></li>)}</ul>
        </div>
      )}

      <div className="card" style={{ marginTop: 16 }}>
        <h2>Skills to work on</h2>
        <p className="muted">Ranked by how many postings ask for it and your resume doesn't show it.</p>
        {learn.length === 0 ? <div className="empty">No recurring skill gaps found.</div> : (() => {
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

function download(name: string, mime: string, body: string) {
  const url = URL.createObjectURL(new Blob([body], { type: mime }));
  const el = document.createElement("a"); el.href = url; el.download = name; document.body.append(el); el.click(); el.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function exportCsv(t: number, jobs: ScoredJob[]) {
  const esc = (v: unknown) => { let s = String(v ?? ""); if (/^[=+\-@]/.test(s)) s = "'" + s; return `"${s.replace(/"/g, '""')}"`; };
  const rows = [["Title", "Company", "Location", "Match %", "Rules-only %", "AI verified reqs", "Qualified", "Requirements met", "Missing required skills", "Blockers", "Sources", "URL"],
    ...jobs.map((j) => [j.title, j.company, j.location, j.score, j.score_det ?? j.score, j.deep ? `${j.deep.verified}/${j.deep.assessed}` : "", qualifies(j, t) ? "yes" : "no",
      `${j.requirements_met}/${j.requirements.length}`, j.required_missing.join("; "), j.blockers.join("; "), j.sources.join("; "), safeUrl(j.url)])];
  download("cv-match-report.csv", "text/csv", rows.map((r) => r.map(esc).join(",")).join("\n"));
}
function exportJson(a: Analysis, t: number) {
  download("cv-match-report.json", "application/json", JSON.stringify({ threshold: t, query: a.query, summary: a.summary, insights: a.insights, jobs: a.jobs }, null, 2));
}

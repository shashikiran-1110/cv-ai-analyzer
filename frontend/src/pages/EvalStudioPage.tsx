import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, CircleX, FlaskConical, Play, ShieldCheck, ThumbsDown, ThumbsUp, Upload } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, post } from "../api";
import { Sparkline } from "../components/charts";
import { Modal } from "../components/Modal";
import { isTyping } from "../components/shell/ShellProvider";
import { Skeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import type { EvalOverview, EvalRun, EvalRunDetail, FeedbackItem, FeedbackSummary, LabelItem } from "../types";

type Tab = "overview" | "runs" | "leaderboard" | "labelling" | "feedback";
const TABS: [Tab, string][] = [["overview", "Overview"], ["runs", "Runs"], ["leaderboard", "Model leaderboard"], ["labelling", "Labelling"], ["feedback", "User feedback"]];
const fmt = (v: unknown) => (v === null || v === undefined ? "—" : typeof v === "number" ? (Number.isInteger(v) ? String(v) : v.toFixed(3)) : String(v));
const when = (t: number) => new Date(t * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

/** Eval Studio: is the AI getting better or worse, what does each model cost, and what do users say? */
export function EvalStudioPage() {
  const [params, setParams] = useSearchParams();
  const tab = (TABS.some(([k]) => k === params.get("tab")) ? params.get("tab") : "overview") as Tab;
  const ov = useQuery({ queryKey: ["eval-overview"], queryFn: () => api<EvalOverview>("/api/eval/overview") });
  return (
    <section aria-labelledby="h-eval">
      <div className="page-head">
        <div><div className="eyebrow"><FlaskConical size={13} aria-hidden="true" />Tools</div>
          <h1 id="h-eval">Eval Studio</h1>
          <p className="lead">Measures every AI component against gold data. <b>Mock</b> runs use a deliberately adversarial model to prove the server's defenses hold (they must stay at 0); <b>record / replay / live</b> runs measure a real model's quality and cost.</p></div>
      </div>
      <div className="tabs" role="tablist">
        {TABS.map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""}
          onClick={() => setParams(k === "overview" ? {} : { tab: k })}>{l}{k === "labelling" && ov.data ? <span className="count">{ov.data.labels.queue}</span> : null}</button>)}
      </div>
      {ov.isError && <div className="alert error">{(ov.error as Error).message}</div>}
      {tab === "overview" && (ov.data ? <Overview o={ov.data} /> : <Skeleton rows={6} />)}
      {tab === "runs" && <Runs />}
      {tab === "leaderboard" && (ov.data ? <Leaderboard o={ov.data} /> : <Skeleton rows={4} />)}
      {tab === "labelling" && <Labelling />}
      {tab === "feedback" && <Feedback />}
    </section>
  );
}

function Overview({ o }: { o: EvalOverview }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [busy, setBusy] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const runs = useQuery({ queryKey: ["eval-runs"], queryFn: () => api<EvalRun[]>("/api/eval/runs?limit=500") });
  const trend = (suite: string, metric: string) => (runs.data ?? []).filter((r) => r.suite === suite && (r.mode === "mock" || r.mode === "deterministic"))
    .map((r) => r.metrics[metric]).filter((v): v is number => typeof v === "number").reverse().slice(-20);
  async function run(suite: string, mode: string) {
    setBusy(`${suite}:${mode}`);
    try {
      const r = await post<EvalRunDetail>("/api/eval/run", { suite, mode });
      toast(`${suite}: ${r.failed} of ${r.cases} cases failed.`, r.failed ? "info" : "ok");
      void qc.invalidateQueries({ queryKey: ["eval-overview"] }); void qc.invalidateQueries({ queryKey: ["eval-runs"] });
    } catch (e) { toast((e as Error).message, "error"); } finally { setBusy(""); }
  }
  async function runAll() {
    setBusy("all");
    let failed = 0;
    for (const s of o.suites) {
      try { const r = await post<EvalRunDetail>("/api/eval/run", { suite: s.suite, mode: s.kind === "llm" ? "mock" : "deterministic" }); failed += r.failed ? 1 : 0; }
      catch { failed++; }
    }
    toast(`Ran ${o.suites.length} suites (deterministic + mock).`, failed ? "info" : "ok");
    void qc.invalidateQueries({ queryKey: ["eval-overview"] }); void qc.invalidateQueries({ queryKey: ["eval-runs"] });
    setBusy("");
  }
  const defense = o.headline.filter((h) => h.target === 0);
  const quality = o.headline.filter((h) => h.target !== 0);
  return (
    <>
      <div className="actions" style={{ marginBottom: 4 }}>
        <button className="btn primary" disabled={!!busy} onClick={runAll}><Play aria-hidden="true" />{busy === "all" ? "Running all suites…" : "Run all free checks"}</button>
        <small className="muted">Deterministic suites + LLM suites against the mock model. No key, no cost.</small>
      </div>
      <h3 className="sec"><ShieldCheck aria-hidden="true" />Defense invariants <small className="muted">(must be 0: what the server lets through, even against an adversarial model)</small></h3>
      <div className="eval-grid">
        {defense.map((h) => {
          const bad = h.value !== null && h.value > 0;
          return (
            <div key={h.key} className={`metric-card ${bad ? "bad" : ""}`}>
              <div className="m-name"><span>{h.suite.replace("llm_", "")}</span>{h.value === null ? <span>not run</span> : bad ? <CircleX size={14} color="var(--bad)" /> : <CircleCheck size={14} color="var(--good)" />}</div>
              <div className="m-val">{fmt(h.value)}</div>
              <div className="m-target">{h.label} · target 0</div>
            </div>);
        })}
      </div>
      <h3 className="sec">Regression gates <small className="muted">(deterministic suites; CI fails if a value gets worse than its baseline)</small></h3>
      <div className="eval-grid">
        {quality.map((h) => {
          const worse = h.value !== null && h.baseline !== null && (h.direction === "+" ? h.value < h.baseline : h.value > h.baseline);
          const tr = trend(h.suite, h.key.split(".").slice(1).join("."));
          return (
            <div key={h.key} className={`metric-card ${worse ? "bad" : ""}`}>
              <div className="m-name"><span>{h.suite} · {h.label}</span><span>{h.direction === "+" ? "higher is better" : "lower is better"}</span></div>
              <div className="m-val">{fmt(h.value)}<small className="muted">baseline {fmt(h.baseline)}</small></div>
              <Sparkline values={tr} label={`${h.key} over the last ${tr.length} runs`} />
            </div>);
        })}
      </div>
      <h3 className="sec">Suites</h3>
      <div className="card flush">
        <div className="dt-wrap" style={{ maxHeight: "none" }}>
          <table className="dt">
            <thead><tr><th>Suite</th><th>Type</th><th>Last run</th><th>Result</th><th /></tr></thead>
            <tbody>
              {o.suites.map((s) => (
                <tr key={s.suite} onClick={() => s.last_run && setOpen(s.last_run.id)} style={{ cursor: s.last_run ? "pointer" : "default" }}>
                  <td><span className="t-title">{s.suite}</span><span className="t-sub" style={{ whiteSpace: "normal" }}>{s.description}</span></td>
                  <td className="muted-cell">{s.kind}</td>
                  <td className="muted-cell">{s.last_run ? `${when(s.last_run.created_at)} · ${s.last_run.mode}${s.last_run.mode === "mock" || s.last_run.mode === "deterministic" ? "" : ` · ${s.last_run.model}`}` : "never"}</td>
                  <td className="muted-cell">{s.last_run ? `${s.last_run.cases - s.last_run.failed}/${s.last_run.cases} passed` : "—"}</td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <div className="actions" style={{ flexWrap: "nowrap" }}>
                      <button className="btn small" disabled={!!busy} onClick={() => run(s.suite, s.kind === "llm" ? "mock" : "deterministic")}>
                        <Play aria-hidden="true" />{busy === `${s.suite}:${s.kind === "llm" ? "mock" : "deterministic"}` ? "Running…" : s.kind === "llm" ? "Mock" : "Run"}</button>
                      {s.kind === "llm" && <button className="btn small ghost" disabled={!!busy} title="Re-run saved real-model responses (record them first from the CLI)"
                        onClick={() => run(s.suite, "replay")}>{busy === `${s.suite}:replay` ? "Running…" : "Replay"}</button>}
                    </div>
                  </td>
                </tr>))}
            </tbody>
          </table>
        </div>
      </div>
      <p className="fine">Real-model runs spend money, so they're started from the CLI: <code>python -m eval.run --suite llm --mode record --model gpt-5.6-luna</code>, then <code>--mode replay</code> re-runs them for free.</p>
      {open && <RunDetail id={open} onClose={() => setOpen(null)} />}
    </>
  );
}

function Runs() {
  const [suite, setSuite] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const q = useQuery({ queryKey: ["eval-runs", suite], queryFn: () => api<EvalRun[]>(`/api/eval/runs?limit=300${suite ? `&suite=${suite}` : ""}`) });
  const suites = useMemo(() => [...new Set((q.data ?? []).map((r) => r.suite))].sort(), [q.data]);
  return (
    <div className="card flush">
      <div className="dt-toolbar">
        <select value={suite} onChange={(e) => setSuite(e.target.value)} aria-label="Suite"><option value="">All suites</option>{suites.map((s) => <option key={s}>{s}</option>)}</select>
        <span className="spacer" /><span className="dt-meta">{q.data?.length ?? 0} runs</span>
      </div>
      {q.isLoading ? <div style={{ padding: 16 }}><Skeleton rows={5} /></div> : (
        <div className="dt-wrap">
          <table className="dt">
            <thead><tr><th>When</th><th>Suite</th><th>Mode</th><th>Model</th><th>Passed</th><th>Cost</th><th>p95</th><th>Commit</th></tr></thead>
            <tbody>{(q.data ?? []).map((r) => (
              <tr key={r.id} onClick={() => setOpen(r.id)}>
                <td className="muted-cell">{when(r.created_at)}</td><td><span className="t-title">{r.suite}</span></td>
                <td className="muted-cell">{r.mode}</td><td className="muted-cell">{r.model}</td>
                <td className="muted-cell">{r.cases - r.failed}/{r.cases}</td>
                <td className="muted-cell">{r.cost_usd == null ? "—" : `$${r.cost_usd.toFixed(4)}`}</td>
                <td className="muted-cell">{r.latency_p95_ms == null ? "—" : `${(r.latency_p95_ms / 1000).toFixed(1)}s`}</td>
                <td className="muted-cell"><code>{r.git_sha || "—"}</code></td>
              </tr>))}</tbody>
          </table>
          {q.data?.length === 0 && <div className="dt-empty">No runs yet. Start one from the Overview tab or the CLI.</div>}
        </div>)}
      {open && <RunDetail id={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function RunDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const q = useQuery({ queryKey: ["eval-run", id], queryFn: () => api<EvalRunDetail>(`/api/eval/runs/${id}`) });
  const [onlyFail, setOnlyFail] = useState(true);
  const r = q.data;
  const cases = (r?.cases_detail ?? []).filter((c) => !onlyFail || !c.passed);
  return (
    <Modal title={r ? `${r.suite} · ${r.mode}` : "Eval run"} onClose={onClose} sheet
      subtitle={r && <div className="job-sub" style={{ marginTop: 4 }}>{when(r.created_at)} · {r.model} · {r.cases - r.failed}/{r.cases} passed{r.git_sha ? ` · ${r.git_sha}` : ""}</div>}>
      {!r ? <Skeleton rows={6} /> : <>
        <h3 className="sec" style={{ marginTop: 0 }}>Metrics</h3>
        <dl className="kv">{Object.entries(r.metrics).map(([k, v]) => <div key={k} style={{ display: "contents" }}><dt>{k}</dt><dd className="num-t">{fmt(v)}</dd></div>)}</dl>
        {Object.keys(r.prompt_versions).length > 0 && <p className="fine" style={{ marginTop: 8 }}>Prompt versions: {Object.entries(r.prompt_versions).map(([k, v]) => `${k} v${v}`).join(", ")}</p>}
        <h3 className="sec">Cases <label className="check small" style={{ marginLeft: "auto" }}><input type="checkbox" checked={onlyFail} onChange={(e) => setOnlyFail(e.target.checked)} />failing only</label></h3>
        <div className="stack" style={{ gap: 8 }}>
          {cases.length === 0 && <p className="muted">{onlyFail ? "No failing cases." : "No cases recorded."}</p>}
          {cases.slice(0, 80).map((c) => (
            <div key={c.case_id} className="case">
              <div className="case-head">{c.passed ? <CircleCheck size={14} color="var(--good)" /> : <CircleX size={14} color="var(--bad)" />}<b>{c.case_id}</b>
                {typeof c.detail.ms === "number" && <small className="muted">{c.detail.ms} ms</small>}</div>
              <pre>{JSON.stringify(c.detail.why ?? c.detail.error ?? c.detail, null, 2)}</pre>
            </div>))}
        </div>
      </>}
    </Modal>
  );
}

function Leaderboard({ o }: { o: EvalOverview }) {
  const rows = [...o.leaderboard].sort((a, b) => a.suite.localeCompare(b.suite) || (b.quality ?? -1) - (a.quality ?? -1));
  return (
    <>
      <p className="muted">Latest real-model run per suite and model (record / replay / live). Quality is the suite's headline metric; check its direction in the run details.</p>
      {rows.length === 0 ? (
        <div className="card empty-state"><FlaskConical aria-hidden="true" /><h2>No real-model runs yet</h2>
          <p className="muted">Record one with your key, then compare models here:</p>
          <pre className="desc" style={{ textAlign: "left", maxWidth: 680, margin: "0 auto" }}>{"OPENAI_API_KEY=sk-… python -m eval.run --suite llm --mode record --model gpt-5.6-luna\nANTHROPIC_API_KEY=… python -m eval.run --suite llm --mode record --provider anthropic --model claude-sonnet-5-5"}</pre></div>
      ) : (
        <div className="card flush"><div className="dt-wrap" style={{ maxHeight: "none" }}>
          <table className="dt lb-table">
            <thead><tr><th>Suite</th><th>Model</th><th>Quality</th><th>Metric</th><th>$ / 100 cases</th><th>p95 latency</th><th>Runs</th></tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={`${r.suite}-${r.model}`} style={{ cursor: "default" }}>
                <td className="muted-cell">{r.suite}</td><td className="model">{r.model}</td><td className="num-t"><b>{fmt(r.quality)}</b></td>
                <td className="muted-cell">{r.quality_metric}</td><td className="muted-cell">{r.cost_per_100 == null ? "—" : `$${r.cost_per_100.toFixed(3)}`}</td>
                <td className="muted-cell">{r.p95_ms == null ? "—" : `${(r.p95_ms / 1000).toFixed(1)}s`}</td><td className="muted-cell">{r.runs}</td>
              </tr>))}</tbody>
          </table>
        </div></div>)}
    </>
  );
}

const LABELS: [string, string, string][] = [["strong", "Strong", "1"], ["possible", "Possible", "2"], ["stretch", "Stretch", "3"], ["no", "No", "4"]];

function Labelling() {
  const qc = useQueryClient();
  const toast = useToast();
  const [reviewer, setReviewer] = useState(() => { try { return localStorage.getItem("cvm.reviewer") || ""; } catch { return ""; } });
  const q = useQuery({ queryKey: ["eval-queue"], queryFn: () => api<{ items: LabelItem[]; stats: EvalOverview["labels"] }>("/api/eval/labels/queue?limit=5") });
  const item = q.data?.items[0];
  async function send(label: string | null) {
    if (!item) return;
    try {
      await post("/api/eval/labels", label ? { id: item.id, label, reviewer } : { id: item.id, skip: true, reviewer });
      void qc.invalidateQueries({ queryKey: ["eval-queue"] }); void qc.invalidateQueries({ queryKey: ["eval-overview"] });
    } catch (e) { toast((e as Error).message, "error"); }
  }
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e) || e.metaKey || e.ctrlKey || document.querySelector(".overlay, .cmdk-overlay")) return;
      const l = LABELS.find(([, , k]) => k === e.key);
      if (l) { e.preventDefault(); void send(l[0]); }
      if (e.key === "s") { e.preventDefault(); void send(null); }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  });
  const s = q.data?.stats;
  return (
    <>
      <div className="kpis">
        <div className="kpi"><span className="k-label">Reviewed pairs</span><b>{s?.reviewed ?? "—"}<small> / 300 needed</small></b><div className="k-sub">to fit and calibrate the score weights</div></div>
        <div className="kpi"><span className="k-label">In queue</span><b>{s?.queue ?? "—"}</b><div className="k-sub">disagreements + 20% audit</div></div>
        <div className="kpi"><span className="k-label">Double-labelled</span><b>{s?.double_labelled ?? "—"}</b><div className="k-sub">pairs with 2 reviewers</div></div>
        <div className="kpi"><span className="k-label">Agreement (Cohen's κ)</span><b>{s?.kappa == null ? "—" : s.kappa.toFixed(2)}</b><div className="k-sub">target ≥ 0.60</div></div>
      </div>
      <div className="toolbar">
        <label className="inline-field"><small>Reviewer</small><input value={reviewer} placeholder="your initials" style={{ width: 140 }}
          onChange={(e) => { setReviewer(e.target.value); try { localStorage.setItem("cvm.reviewer", e.target.value); } catch { /* blocked */ } }} /></label>
        <small className="muted">Label how well this candidate fits the job, as a careful recruiter would. Keys: <kbd>1</kbd>–<kbd>4</kbd>, <kbd>s</kbd> to skip.</small>
      </div>
      {q.isLoading && <Skeleton rows={6} />}
      {!q.isLoading && !item && <div className="card empty-state"><CircleCheck aria-hidden="true" /><h2>Queue is empty</h2>
        <p className="muted">Build and pre-label more pairs: <code>python -m eval.labeling.build_pairs …</code> then <code>python -m eval.labeling.prelabel … --queue eval/datasets/match/queue.jsonl</code>.</p></div>}
      {item && (
        <div className="card">
          <div className="card-head"><div><h2>{item.job_title}</h2><small>{item.occupation ?? ""}{item.synthetic ? " · synthetic resume" : ""} · {item.reason ?? ""}</small></div></div>
          {item.prelabels.length > 0 && <div className="chips">{item.prelabels.map((p) => <span key={p.model} className="chip" title={p.rationale}>{p.model}: <b>{p.label}</b></span>)}</div>}
          <div className="label-pane">
            <div><div className="pane-title"><span>Resume</span></div><pre className="desc">{item.resume}</pre></div>
            <div><div className="pane-title"><span>Job posting</span></div><pre className="desc">{item.job_description}</pre></div>
          </div>
          <div className="label-btns" style={{ marginTop: 14 }}>
            {LABELS.map(([v, l, k]) => <button key={v} className="btn" onClick={() => send(v)}>{l}<kbd>{k}</kbd></button>)}
            <button className="btn ghost" onClick={() => send(null)}>Skip<kbd>s</kbd></button>
          </div>
        </div>)}
    </>
  );
}

function Feedback() {
  const toast = useToast();
  const qc = useQueryClient();
  const sum = useQuery({ queryKey: ["fb-summary"], queryFn: () => api<FeedbackSummary[]>("/api/feedback/summary") });
  const list = useQuery({ queryKey: ["fb-list"], queryFn: () => api<FeedbackItem[]>("/api/feedback?limit=100") });
  async function promote(id: number) {
    try {
      const r = await post<{ promoted: boolean; message?: string; path?: string }>(`/api/feedback/${id}/promote`, {});
      toast(r.promoted ? `Added to ${r.path} for review.` : r.message || "Already promoted.", "ok");
      void qc.invalidateQueries({ queryKey: ["fb-list"] });
    } catch (e) { toast((e as Error).message, "error"); }
  }
  return (
    <>
      <p className="muted">Thumbs and corrections from the app's AI outputs. Corrections to a requirement's status re-score that job immediately; promote any item to turn it into an eval case.</p>
      <div className="eval-grid">
        {(sum.data ?? []).map((s) => (
          <div key={s.kind} className="metric-card">
            <div className="m-name"><span>{s.kind.replace("_", " ")}</span><span>{s.total} ratings</span></div>
            <div className="m-val">{s.approval == null ? "—" : `${Math.round(s.approval * 100)}%`}<small className="muted">helpful</small></div>
            <div className="m-target"><ThumbsUp size={11} /> {s.up} · <ThumbsDown size={11} /> {s.down} · {s.corrections} correction{s.corrections === 1 ? "" : "s"}</div>
          </div>))}
        {sum.data?.length === 0 && <p className="muted">No feedback yet. Rate AI outputs in a report (deep checks, advice, chat, drafts) to see them here.</p>}
      </div>
      {(list.data?.length ?? 0) > 0 && (
        <div className="card flush"><div className="dt-wrap">
          <table className="dt">
            <thead><tr><th>When</th><th>Kind</th><th>Rating</th><th>Item</th><th>Comment / correction</th><th /></tr></thead>
            <tbody>{list.data!.map((f) => (
              <tr key={f.id} style={{ cursor: "default" }}>
                <td className="muted-cell">{when(f.created_at)}</td><td className="muted-cell">{f.kind}</td>
                <td>{f.rating > 0 ? <ThumbsUp size={14} color="var(--good)" /> : f.rating < 0 ? <ThumbsDown size={14} color="var(--bad)" /> : "—"}</td>
                <td><span className="t-sub" style={{ maxWidth: 260 }} title={f.item_id}>{f.item_id || "—"}</span></td>
                <td><span className="t-sub" style={{ maxWidth: 320 }}>{f.correction ? `→ ${String((f.correction as { status?: string }).status ?? JSON.stringify(f.correction))}` : ""}{f.comment ? ` ${f.comment}` : ""}</span></td>
                <td>{f.promoted ? <small className="muted">promoted</small> : <button className="btn small ghost" onClick={() => promote(f.id)}><Upload aria-hidden="true" />Promote</button>}</td>
              </tr>))}</tbody>
          </table>
        </div></div>)}
    </>
  );
}

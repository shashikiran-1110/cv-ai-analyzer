import { useState } from "react";
import { useAi } from "../ai";
import { post } from "../api";
import type { SearchParams, SearchPlan } from "../types";
import { Alert } from "./ui";

const LEVEL: Record<string, string> = { internship: "Internship", entry: "Entry", associate: "Associate", mid_senior: "Mid–senior", director: "Director", executive: "Executive" };

/** Search Planner (ROADMAP §8.6): describe the role in plain words → an editable plan applied to the search form. */
export function PlanCard({ params, onApply }: { params: SearchParams; onApply: (p: Partial<SearchParams>) => void }) {
  const ai = useAi();
  const [intent, setIntent] = useState("");
  const [plan, setPlan] = useState<SearchPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [extra, setExtra] = useState("");

  async function make() {
    setBusy(true); setErr("");
    try { setPlan(await post<SearchPlan>("/api/plan", { intent: intent.trim() }, ai.headers)); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  const drop = (k: "alt_titles" | "exclude_titles", t: string) => plan && setPlan({ ...plan, [k]: plan[k].filter((x) => x !== t) });
  function apply() {
    if (!plan) return;
    onApply({ title: plan.title, location: plan.location || params.location, alt_titles: plan.alt_titles, exclude_titles: plan.exclude_titles,
      experience: plan.seniority.length ? plan.seniority : params.experience, workplace: plan.workplace.length ? plan.workplace : params.workplace });
    setPlan(null); setIntent("");
  }
  const active = (params.alt_titles?.length ?? 0) + (params.exclude_titles?.length ?? 0);
  return (
    <div className="plan-card">
      <div className="plan-row">
        <input value={intent} onChange={(e) => setIntent(e.target.value)} maxLength={500} aria-label="Describe the role"
          placeholder="Or describe it: “senior ML engineer, Bangalore or remote”" onKeyDown={(e) => { if (e.key === "Enter" && intent.trim().length > 2) { e.preventDefault(); void make(); } }} />
        <button type="button" className="btn small" disabled={busy || intent.trim().length < 3} onClick={make}>{busy ? "Planning…" : ai.usable ? "✦ Plan with AI" : "Plan"}</button>
      </div>
      {err && <Alert>{err}</Alert>}
      {plan && (
        <div className="plan-out enter" data-testid="plan">
          <div className="plan-head"><b>{plan.title}</b>{plan.location && <span className="muted"> · {plan.location}</span>}
            <small className="muted"> · {plan.source === "rules" ? "built-in plan" : "AI plan"}</small></div>
          {plan.ai_error && <small className="warn-text">AI unavailable ({plan.ai_error}); showing the built-in plan.</small>}
          <div className="plan-sec"><small>Also counts as a match</small>
            <div className="chips">{plan.alt_titles.map((t) => <span key={t} className="chip ok">{t}<button className="x" aria-label={`Remove ${t}`} onClick={() => drop("alt_titles", t)}>×</button></span>)}
              <input className="chip-input" value={extra} placeholder="+ title" onChange={(e) => setExtra(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && extra.trim()) { e.preventDefault(); setPlan({ ...plan, alt_titles: [...plan.alt_titles, extra.trim()] }); setExtra(""); } }} /></div></div>
          {plan.exclude_titles.length > 0 && <div className="plan-sec"><small>Excluded look-alikes</small>
            <div className="chips">{plan.exclude_titles.map((t) => <span key={t} className="chip miss">{t}<button className="x" aria-label={`Remove ${t}`} onClick={() => drop("exclude_titles", t)}>×</button></span>)}</div></div>}
          {(plan.seniority.length > 0 || plan.workplace.length > 0) && <div className="plan-sec"><small>Filters</small>
            <div className="chips">{plan.seniority.map((s) => <span key={s} className="chip">{LEVEL[s] ?? s}</span>)}{plan.workplace.map((w) => <span key={w} className="chip">{w.replace("_", "-")}</span>)}</div></div>}
          {plan.dropped_titles && plan.dropped_titles.length > 0 && <small className="muted">Dropped as a different job: {plan.dropped_titles.join(", ")}</small>}
          {plan.note && <small className="muted">{plan.note}</small>}
          <div className="actions"><button className="btn small primary" onClick={apply}>Use this plan</button><button className="btn small" onClick={() => setPlan(null)}>Discard</button></div>
        </div>
      )}
      {!plan && active > 0 && <small className="muted">Plan active: {params.alt_titles?.length ?? 0} extra title(s){params.exclude_titles?.length ? `, ${params.exclude_titles.length} excluded` : ""}. <button className="link" onClick={() => onApply({ alt_titles: [], exclude_titles: [] })}>Clear</button></small>}
    </div>
  );
}

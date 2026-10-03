import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { SkillPicker } from "../components/SkillPicker";
import { Skeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { Alert } from "../components/ui";
import type { Corrections, ProfileRole, ProfileView, RoleFix } from "../types";

const STRENGTH_ORDER = ["strong", "moderate", "user", "weak"];
const STRENGTH_LABEL: Record<string, string> = {
  strong: "Strong: used in 2+ experience bullets", moderate: "Moderate: one role or a project",
  weak: "Listed only: no work or project evidence", user: "Added by you",
};
const ym = (s: string) => (s === "present" ? "Present" : s ? new Date(`${s}-01T00:00:00`).toLocaleDateString(undefined, { month: "short", year: "numeric" }) : "?");
const yrs = (m: number) => `${(m / 12).toFixed(1)} yrs`;

/** Profile review (ROADMAP §5.3): see exactly what the matcher read, and fix it. Fixes apply to every analysis. */
export function ProfilePage() {
  const { rid = "" } = useParams();
  const [params] = useSearchParams();
  const back = params.get("from");
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["profile", rid], queryFn: () => api<ProfileView>(`/api/profiles/${rid}`) });
  const [draft, setDraft] = useState<Corrections | null>(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (q.data && draft === null) setDraft(q.data.corrections); }, [q.data, draft]);

  const dirty = useMemo(() => !!q.data && !!draft && JSON.stringify(draft) !== JSON.stringify(q.data.corrections), [q.data, draft]);

  if (q.isPending || !draft) return <section className="enter"><h1>Your profile</h1><Skeleton rows={8} /></section>;
  if (q.isError) return <section className="enter"><h1>Your profile</h1><Alert>{(q.error as Error).message}</Alert><Link className="btn" to="/">Upload a resume</Link></section>;
  const v = q.data;
  const p = v.profile;

  const role = (id: string): RoleFix => draft.roles?.[id] ?? {};
  const setRole = (id: string, fix: RoleFix) => setDraft({ ...draft, roles: { ...(draft.roles ?? {}), [id]: { ...role(id), ...fix } } });
  const removed = new Set((draft.skills_remove ?? []).map((s) => s.toLowerCase()));
  const toggleSkill = (name: string) => setDraft({
    ...draft, skills_remove: removed.has(name.toLowerCase()) ? (draft.skills_remove ?? []).filter((s) => s.toLowerCase() !== name.toLowerCase()) : [...(draft.skills_remove ?? []), name],
  });

  async function save() {
    setSaving(true);
    try {
      const clean: Corrections = { ...draft };
      if (clean.years_override === undefined || Number.isNaN(clean.years_override)) delete clean.years_override;
      const r = await api<ProfileView>(`/api/profiles/${rid}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(clean) });
      qc.setQueryData(["profile", rid], r);
      setDraft(r.corrections);
      void qc.invalidateQueries({ queryKey: ["analysis"] });
      toast("Profile saved. Analyses use your corrections from now on.", "ok");
    } catch (e) { toast((e as Error).message, "error"); } finally { setSaving(false); }
  }

  const groups = STRENGTH_ORDER.map((s) => [s, p.skills.filter((x) => x.strength === s)] as const).filter(([, xs]) => xs.length);
  const okCount = v.formatting.filter((c) => c.ok).length;
  return (
    <section className="enter profile-page" aria-labelledby="h-profile">
      <div className="head-row">
        <div><h1 id="h-profile">What the matcher read from your resume</h1>
          <p className="lead">{p.headline || "Resume"} · {yrs(p.experience_months.total)} counted · {p.education_level ?? "no degree found"} · parse confidence {Math.round(p.parse.confidence * 100)}%</p></div>
        <div className="actions">
          {back && <Link className="btn" to={back}>← Back to report</Link>}
          <button className="btn" disabled={!dirty || saving} onClick={() => setDraft(v.corrections)}>Undo changes</button>
          <button className="btn primary" disabled={!dirty || saving} onClick={save}>{saving ? "Saving…" : "Save corrections"}</button>
        </div>
      </div>
      {p.parse.warnings.map((w) => <Alert kind="warn" key={w}>{w}</Alert>)}
      {dirty && <Alert kind="info">Unsaved changes. After saving, open your report and it re-scores with the corrected profile.</Alert>}

      <div className="cols profile-cols">
        <div>
          <div className="card">
            <h2>Work history</h2>
            <p className="muted">Only these roles count toward years of experience (overlaps counted once). Fix wrong titles or dates, or exclude a role.</p>
            {p.roles.length === 0 && <Alert kind="warn">No dated roles found. Add month–year ranges like “Jan 2021 – Present” to each job on your resume, or set your years below.</Alert>}
            <ol className="timeline">
              {p.roles.map((r: ProfileRole) => {
                const fix = role(r.id);
                const off = !!fix.ignore;
                return (
                  <li key={r.id} className={off ? "off" : ""}>
                    <div className="tl-dot" aria-hidden="true" />
                    <div className="tl-body">
                      <div className="tl-row">
                        <input aria-label="Job title" value={fix.title ?? r.title} onChange={(e) => setRole(r.id, { title: e.target.value })} />
                        <input aria-label="Company" value={fix.company ?? r.company} onChange={(e) => setRole(r.id, { company: e.target.value })} />
                      </div>
                      <div className="tl-row small">
                        <label>From <input type="month" value={fix.start ?? r.start} onChange={(e) => setRole(r.id, { start: e.target.value || undefined })} /></label>
                        <label>To {(fix.end ?? r.end) === "present"
                          ? <button className="link" onClick={() => setRole(r.id, { end: new Date().toISOString().slice(0, 7) })}>Present (change)</button>
                          : <input type="month" value={fix.end ?? r.end} onChange={(e) => setRole(r.id, { end: e.target.value || undefined })} />}</label>
                        <span className="muted">{ym(fix.start ?? r.start)} – {ym(fix.end ?? r.end)} · {r.months} mo{r.date_precision === "year" ? " (year-only dates)" : ""}</span>
                        <label className="check"><input type="checkbox" checked={off} onChange={(e) => setRole(r.id, { ignore: e.target.checked })} /> Don't count</label>
                      </div>
                      {r.bullets.length > 0 && <details><summary>{r.bullets.length} bullet{r.bullets.length > 1 ? "s" : ""} · {r.bullets.filter((b) => b.metrics?.length).length} with numbers</summary>
                        <ul className="bullets">{r.bullets.map((b) => <li key={b.id}>{b.text}{b.skills.length > 0 && <span className="chips inline">{b.skills.map((s) => <span key={s} className="chip ok">{s}</span>)}</span>}</li>)}</ul>
                      </details>}
                    </div>
                  </li>
                );
              })}
            </ol>
            <div className="row-fields">
              <label className="field"><span>Override total experience (years)</span>
                <input type="number" min={0} max={60} step={0.5} placeholder={(p.experience_months.total / 12).toFixed(1)}
                  value={draft.years_override ?? ""} onChange={(e) => setDraft({ ...draft, years_override: e.target.value === "" ? undefined : Number(e.target.value) })} />
                <small>Leave empty to use the roles above.</small></label>
              <label className="field"><span>Highest degree</span>
                <select value={draft.degree ?? "auto"} onChange={(e) => { const d = { ...draft }; if (e.target.value === "auto") delete d.degree; else d.degree = e.target.value as Corrections["degree"]; setDraft(d); }}>
                  <option value="auto">As read ({v.parsed.education_level ?? "none"})</option>
                  <option value="">None</option><option>Bachelor's</option><option>Master's</option><option>PhD</option>
                </select></label>
            </div>
          </div>
        </div>

        <div>
          <div className="card">
            <h2>Skills by evidence</h2>
            <p className="muted">Skills backed by work bullets are the most convincing. Click a skill to stop the matcher from counting it.</p>
            {groups.map(([strength, xs]) => (
              <div key={strength} className={`skill-group s-${strength}`}>
                <h4>{STRENGTH_LABEL[strength] ?? strength} <span className="muted">({xs.length})</span></h4>
                <div className="chips">{xs.map((s) => (
                  <button key={s.name} className={`chip clickable ${removed.has(s.name.toLowerCase()) ? "struck" : strength === "weak" ? "pref" : "ok"}`}
                    title={s.months_used ? `${yrs(s.months_used)} in roles · last used ${ym(s.last_used)}` : s.source.replace("_", " ")}
                    aria-pressed={removed.has(s.name.toLowerCase())} onClick={() => toggleSkill(s.name)}>{s.name}</button>))}</div>
              </div>
            ))}
            {removed.size > 0 && <small className="muted">Struck-through skills are ignored when matching.</small>}
            <h4>Skills you have that the resume doesn't show</h4>
            <SkillPicker value={draft.skills_add ?? []} onChange={(skills_add) => setDraft({ ...draft, skills_add })} />
          </div>
          <div className="card">
            <h2>Readability check <span className="tag ai">{okCount}/{v.formatting.length}</span></h2>
            <p className="muted">How applicant tracking systems are likely to read this file.</p>
            <ul className="checklist">{v.formatting.map((c) => (
              <li key={c.label}><span aria-hidden="true">{c.ok ? "✅" : "⚠️"}</span><b>{c.label}</b><span>{c.detail}</span></li>))}</ul>
          </div>
        </div>
      </div>
    </section>
  );
}

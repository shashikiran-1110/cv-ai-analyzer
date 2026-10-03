import { useEffect, useMemo, useState } from "react";
import { api, post } from "../api";
import type { SourceInfo } from "../types";

export interface SourceConfig {
  mode: "portals" | "paste" | "sample";
  selected: string[];
  companies: Record<string, string>;
  urls: string;
  adzuna: { app_id: string; app_key: string; country: string };
  usajobs?: { email: string; key: string };
  paste: string;
}
export const DEFAULT_SOURCES: SourceConfig = {
  mode: "portals", selected: ["linkedin", "remotive", "remoteok", "arbeitnow", "jobicy", "himalayas", "themuse"],
  companies: {}, urls: "", adzuna: { app_id: "", app_key: "", country: "gb" }, usajobs: { email: "", key: "" }, paste: "",
};
export const COMPANY_KINDS = ["greenhouse", "lever", "ashby", "smartrecruiters", "workable", "recruitee", "personio", "teamtailor", "workday"];
const COUNTRIES = "gb us at au be br ca ch de es fr in it mx nl nz pl sg za".split(" ");

export interface PastedJob { title: string; company: string; location: string; url: string; description: string }

/** Blocks separated by a line of ---. First line "Title @ Company"; optional "Location:" / "URL:" lines. */
export function parsePasted(text: string): PastedJob[] {
  return text.split(/^\s*-{3,}\s*$/m).map((b) => b.trim()).filter(Boolean).map((block) => {
    const lines = block.split("\n");
    let head = lines.shift()!.trim();
    let company = "", location = "", url = "";
    const m = head.match(/^(.*?)\s+(?:@|at|\||–|-)\s+(.+)$/i);
    if (m) { head = m[1].trim(); company = m[2].trim(); }
    while (lines.length && /^(company|location|url|link)\s*:/i.test(lines[0].trim())) {
      const [k, ...v] = lines.shift()!.split(":");
      const val = v.join(":").trim();
      if (/company/i.test(k)) company = val; else if (/location/i.test(k)) location = val; else url = val;
    }
    return { title: head.slice(0, 200), company, location, url, description: lines.join("\n").trim() };
  });
}

const splitList = (s: string) => s.split(/[\s,]+/).map((x) => x.trim()).filter(Boolean);

export function sourcesProblem(c: SourceConfig): string {
  if (c.mode === "paste") {
    const jobs = parsePasted(c.paste);
    if (!jobs.length) return "Paste at least one job posting.";
    const bad = jobs.findIndex((j) => j.description.length < 50);
    if (bad >= 0) return `Pasted job ${bad + 1} needs a description (at least 50 characters).`;
    return "";
  }
  if (c.mode === "sample") return "";
  if (!c.selected.length) return "Pick at least one source.";
  for (const k of COMPANY_KINDS)
    if (c.selected.includes(k) && !splitList(c.companies[k] ?? "").length) return `Add company slugs for ${k[0].toUpperCase() + k.slice(1)} or untick it.`;
  if (c.selected.includes("urls") && !splitList(c.urls).length) return "Paste at least one job URL or untick “Job URLs”.";
  if (c.selected.includes("adzuna") && !(c.adzuna.app_id && c.adzuna.app_key)) return "Enter your Adzuna App ID and Key, or untick Adzuna.";
  if (c.selected.includes("usajobs") && !(c.usajobs?.email && c.usajobs?.key)) return "Enter your USAJOBS email and API key, or untick USAJOBS.";
  return "";
}

export function sourcesPayload(c: SourceConfig) {
  return {
    sources: c.selected,
    companies: Object.fromEntries(COMPANY_KINDS.filter((k) => c.selected.includes(k)).map((k) => [k, splitList(c.companies[k] ?? "")])),
    urls: c.selected.includes("urls") ? splitList(c.urls) : [],
    adzuna: c.selected.includes("adzuna") ? c.adzuna : null,
    usajobs: c.selected.includes("usajobs") ? c.usajobs : null,
  };
}

export function SourcesPicker({ value, onChange }: { value: SourceConfig; onChange: (c: SourceConfig) => void }) {
  const [list, setList] = useState<SourceInfo[]>([]);
  useEffect(() => { api<SourceInfo[]>("/api/sources").then(setList).catch(() => {}); }, []);
  const set = (patch: Partial<SourceConfig>) => onChange({ ...value, ...patch });
  const toggle = (id: string, on?: boolean) => {
    const has = value.selected.includes(id);
    const want = on ?? !has;
    set({ selected: want ? (has ? value.selected : [...value.selected, id]) : value.selected.filter((x) => x !== id) });
  };
  const groups = useMemo(() => ({
    boards: list.filter((s) => (s.kind === "search" && s.needs === "") || s.kind === "board"),
    company: list.filter((s) => s.kind === "company"),
    adzuna: list.filter((s) => s.needs === "adzuna_key"),
    usajobs: list.filter((s) => s.needs === "usajobs_key"),
    urls: list.filter((s) => s.kind === "url"),
  }), [list]);
  const pasted = value.mode === "paste" ? parsePasted(value.paste) : [];

  return (
    <div className="card setup-card">
      <div className="card-head"><span className="num">3</span><div><h2>Where to look</h2><small>More sources = more postings. Each source fails independently.</small></div></div>
      <div className="seg narrow" role="tablist" aria-label="Job source mode">
        {([["portals", "Search job portals"], ["paste", "Paste jobs"], ["sample", "Sample jobs"]] as const).map(([m, l]) => (
          <button key={m} type="button" role="tab" aria-selected={value.mode === m} aria-checked={value.mode === m} onClick={() => set({ mode: m })}>{l}</button>
        ))}
      </div>

      {value.mode === "portals" && <>
        <h3 className="sec">Job boards</h3>
        <div className="src-grid">
          {groups.boards.map((s) => (
            <label key={s.id} className={`src ${value.selected.includes(s.id) ? "on" : ""}`}>
              <input type="checkbox" checked={value.selected.includes(s.id)} onChange={() => toggle(s.id)} />
              <span><span className="src-name"><b>{s.name}</b>{s.remote_only && <em className="mini">remote</em>}</span><small>{s.note}</small></span>
            </label>
          ))}
        </div>
        <h3 className="sec">Company career boards <small>(official ATS APIs, e.g. stripe, airbnb)</small></h3>
        <CompanyFinder onAdd={(kind, slug) => {
          const cur = splitList(value.companies[kind] ?? "");
          onChange({ ...value, companies: { ...value.companies, [kind]: [...new Set([...cur, slug])].join(", ") },
            selected: value.selected.includes(kind) ? value.selected : [...value.selected, kind] });
        }} />
        <div className="src-grid">
          {groups.company.map((s) => {
            const k = s.id;
            return (
              <div key={s.id} className={`src col ${value.selected.includes(s.id) ? "on" : ""}`}>
                <label className="check"><input type="checkbox" checked={value.selected.includes(s.id)} onChange={() => toggle(s.id)} /><b>{s.name}</b></label>
                <input placeholder="company slugs, comma-separated" value={value.companies[k] ?? ""} aria-label={`${s.name} company slugs`}
                  onChange={(e) => { onChange({ ...value, companies: { ...value.companies, [k]: e.target.value }, selected: e.target.value.trim() && !value.selected.includes(s.id) ? [...value.selected, s.id] : value.selected }); }} />
                <small>{s.note}</small>
              </div>
            );
          })}
        </div>
        <div className="two">
          {groups.adzuna.map((s) => (
            <div key={s.id} className={`src col ${value.selected.includes(s.id) ? "on" : ""}`}>
              <label className="check"><input type="checkbox" checked={value.selected.includes(s.id)} onChange={() => toggle(s.id)} /><b>{s.name}</b><em className="mini">aggregator · free key</em></label>
              <div className="key-row">
                <input placeholder="App ID" value={value.adzuna.app_id} aria-label="Adzuna App ID" onChange={(e) => set({ adzuna: { ...value.adzuna, app_id: e.target.value } })} />
                <input placeholder="App Key" type="password" value={value.adzuna.app_key} aria-label="Adzuna App Key" onChange={(e) => set({ adzuna: { ...value.adzuna, app_key: e.target.value } })} />
                <select value={value.adzuna.country} aria-label="Adzuna country" onChange={(e) => set({ adzuna: { ...value.adzuna, country: e.target.value } })}>
                  {COUNTRIES.map((c) => <option key={c} value={c}>{c.toUpperCase()}</option>)}
                </select>
              </div>
              <small>{s.note}. Get a key at <a href="https://developer.adzuna.com" target="_blank" rel="noopener noreferrer">developer.adzuna.com</a>.</small>
            </div>
          ))}
          {groups.usajobs.map((s) => (
            <div key={s.id} className={`src col ${value.selected.includes(s.id) ? "on" : ""}`}>
              <label className="check"><input type="checkbox" checked={value.selected.includes(s.id)} onChange={() => toggle(s.id)} /><b>{s.name}</b><em className="mini">official · free key</em></label>
              <div className="key-row">
                <input placeholder="Your email" value={value.usajobs?.email ?? ""} aria-label="USAJOBS email" onChange={(e) => set({ usajobs: { key: value.usajobs?.key ?? "", email: e.target.value } })} />
                <input placeholder="API key" type="password" value={value.usajobs?.key ?? ""} aria-label="USAJOBS API key" onChange={(e) => set({ usajobs: { email: value.usajobs?.email ?? "", key: e.target.value } })} />
              </div>
              <small>{s.note}.</small>
            </div>
          ))}
          {groups.urls.map((s) => (
            <div key={s.id} className={`src col ${value.selected.includes(s.id) ? "on" : ""}`}>
              <label className="check"><input type="checkbox" checked={value.selected.includes(s.id)} onChange={() => toggle(s.id)} /><b>{s.name}</b></label>
              <textarea rows={3} placeholder={"https://wellfound.com/jobs/…\nhttps://jobs.lever.co/acme/…\nhttps://www.linkedin.com/jobs/view/…"} value={value.urls} aria-label="Job URLs"
                onChange={(e) => onChange({ ...value, urls: e.target.value, selected: e.target.value.trim() && !value.selected.includes(s.id) ? [...value.selected, s.id] : value.selected })} />
              <small>Up to 25 links. Wellfound has no public API and often blocks automated requests; if it does, use “Paste jobs”.</small>
            </div>
          ))}
        </div>
      </>}

      {value.mode === "paste" && (
        <div className="field">
          <span>Paste job postings <small>(separate jobs with a line containing only ---)</small></span>
          <textarea rows={10} value={value.paste} onChange={(e) => set({ paste: e.target.value })} aria-label="Pasted jobs"
            placeholder={"Senior Data Engineer @ Acme\nLocation: London\nRequirements\n- 5+ years of experience…\n---\nData Engineer @ Globex\n…"} />
          <small>{pasted.length ? `Detected ${pasted.length} job${pasted.length > 1 ? "s" : ""}: ${pasted.map((j) => j.title + (j.company ? ` @ ${j.company}` : "")).join(" · ")}` : "Works for any site (Wellfound, Indeed, company pages): copy the posting text and paste it here."}</small>
        </div>
      )}
      {value.mode === "sample" && <p className="muted">Uses 14 built-in <b>sample</b> postings from fictional companies to try the app end to end without any network access. Not real jobs.</p>}
    </div>
  );
}

type Board = { kind: string; slug: string; jobs: number | null };

/** Company resolver (ROADMAP §4.2): type a company, we find its public ATS board. */
function CompanyFinder({ onAdd }: { onAdd: (kind: string, slug: string) => void }) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<{ name: string; boards: Board[]; note?: string } | null>(null);
  const [err, setErr] = useState("");
  async function find(refresh = false) {
    if (name.trim().length < 2) return;
    setBusy(true); setErr("");
    try { setRes(await post("/api/companies/resolve", { name: name.trim(), refresh })); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  return (
    <div className="finder">
      <div className="plan-row">
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Find a company's job board, e.g. Stripe" aria-label="Company name"
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void find(); } }} />
        <button type="button" className="btn small" onClick={() => find()} disabled={busy || name.trim().length < 2}>{busy ? "Looking…" : "Find"}</button>
      </div>
      {err && <small className="warn-text">{err}</small>}
      {res && <div className="chips" data-testid="finder">
        {res.boards.map((b) => <button type="button" key={b.kind} className="chip clickable ok" onClick={() => onAdd(b.kind, b.slug)}>
          + {b.kind}: {b.slug}{b.jobs != null ? ` (${b.jobs} jobs)` : ""}</button>)}
        {!res.boards.length && <small className="muted">{res.note}</small>}
        <button type="button" className="link small" onClick={() => find(true)}>Check again</button>
      </div>}
    </div>
  );
}

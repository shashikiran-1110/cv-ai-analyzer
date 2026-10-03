import { useMemo, useState } from "react";
import type { JobSummary, SearchQuery } from "../types";
import { safeUrl } from "./ui";

export function JobsStep({ jobs, query, selected, setSelected, onBack, onNext }: {
  jobs: JobSummary[]; query: SearchQuery | null; selected: Set<string>; setSelected: (s: Set<string>) => void;
  onBack: () => void; onNext: () => void;
}) {
  const [filter, setFilter] = useState("");
  const [exclude, setExclude] = useState("");
  const [sort, setSort] = useState("found");

  const visible = useMemo(() => {
    const f = filter.trim().toLowerCase();
    const ex = exclude.split(",").map((x) => x.trim().toLowerCase()).filter(Boolean);
    const rows = jobs.filter((j) => {
      const hay = `${j.title} ${j.company}`.toLowerCase();
      return (!f || hay.includes(f)) && !ex.some((x) => j.title.toLowerCase().includes(x));
    });
    if (sort === "company") rows.sort((a, b) => a.company.localeCompare(b.company));
    if (sort === "title") rows.sort((a, b) => a.title.localeCompare(b.title));
    if (sort === "posted") rows.sort((a, b) => b.posted.localeCompare(a.posted));
    return rows;
  }, [jobs, filter, exclude, sort]);

  const visSelected = visible.filter((j) => selected.has(j.id)).length;
  const toggle = (id: string) => { const n = new Set(selected); n.has(id) ? n.delete(id) : n.add(id); setSelected(n); };
  const setVisible = (on: boolean) => { const n = new Set(selected); visible.forEach((j) => (on ? n.add(j.id) : n.delete(j.id))); setSelected(n); };
  const noDesc = jobs.filter((j) => j.description_missing).length;

  return (
    <section aria-labelledby="h-jobs">
      <div className="head-row">
        <div>
          <h1 id="h-jobs">Jobs found</h1>
          <p className="lead">{jobs.length} postings for “{query?.title}”{query?.location ? ` in ${query.location}` : ""}{noDesc ? ` · ${noDesc} without description text` : ""}</p>
        </div>
        <div className="actions">
          <button className="btn" onClick={onBack}>← New search</button>
          <button className="btn primary" disabled={!selected.size} onClick={onNext}>Continue with {selected.size} jobs →</button>
        </div>
      </div>
      <div className="card">
        <div className="toolbar">
          <label className="check"><input type="checkbox" checked={visible.length > 0 && visSelected === visible.length}
            ref={(el) => { if (el) el.indeterminate = visSelected > 0 && visSelected < visible.length; }}
            onChange={(e) => setVisible(e.target.checked)} /> Select shown</label>
          <input type="search" placeholder="Filter by title or company…" aria-label="Filter jobs" value={filter} onChange={(e) => setFilter(e.target.value)} />
          <input type="text" placeholder="Hide titles containing… (comma-separated)" aria-label="Hide titles containing" value={exclude} onChange={(e) => setExclude(e.target.value)} />
          <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort jobs">
            <option value="found">Order found</option><option value="posted">Newest</option><option value="company">Company</option><option value="title">Title</option>
          </select>
        </div>
        <ul className="joblist">
          {visible.length === 0 && <li className="empty">No jobs match those filters.</li>}
          {visible.map((j) => (
            <li key={j.id}>
              <input type="checkbox" aria-label={`Include ${j.title} at ${j.company}`} checked={selected.has(j.id)} onChange={() => toggle(j.id)} />
              <div className="job-main">
                <div className="job-title"><a href={safeUrl(j.url)} target="_blank" rel="noopener noreferrer">{j.title}</a>
                  {j.description_missing && <span className="pill" title="No description could be loaded; the match will be a rough estimate">no description</span>}</div>
                <div className="job-sub">{[j.company, j.location, j.seniority, j.employment_type, j.posted].filter(Boolean).join(" · ")}</div>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

import {
  flexRender, getCoreRowModel, getSortedRowModel, useReactTable,
  type ColumnDef, type RowSelectionState, type SortingState, type VisibilityState,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ArrowDown, ArrowUp, ArrowUpDown, Bookmark, Columns3, Download, GitCompareArrows, ListFilter, Rows2, Rows3, Search, ShieldCheck, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import type { ScoredJob } from "../../types";
import { isTyping } from "../shell/ShellProvider";
import { SourceBadges, sourceName } from "../SourceBadge";

export type JobStatus = "qualified" | "gate" | "below";
export const qualifies = (j: Pick<ScoredJob, "score" | "gates_failed">, t: number) => j.score >= t && !(j.gates_failed?.length);
export const statusOf = (j: ScoredJob, t: number): JobStatus => (qualifies(j, t) ? "qualified" : j.score >= t ? "gate" : "below");
const tone = (s: number, t: number) => (s >= t ? "hi" : s >= t - 15 ? "mid" : "lo");

export function relTime(iso: string): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso.slice(0, 10);
  const d = (Date.now() - t) / 86400000;
  return d < 1 ? "today" : d < 2 ? "1d ago" : d < 30 ? `${Math.floor(d)}d ago` : d < 365 ? `${Math.floor(d / 30)}mo ago` : `${Math.floor(d / 365)}y ago`;
}
const workplace = (j: ScoredJob) => (j.remote === true ? "remote" : j.remote === false ? "on-site" : "unknown");

export interface BulkActions {
  verify: (ids: string[]) => void;
  save: (jobs: ScoredJob[]) => void;
  compare: (ids: string[]) => void;
  exportCsv: (jobs: ScoredJob[]) => void;
  verifyHint?: (n: number) => string;
}

function Facet({ label, options, value, onChange, align }: {
  label: string; options: { v: string; label: string; n: number }[]; value: string[]; onChange: (v: string[]) => void; align?: "right";
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close); document.addEventListener("keydown", close);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", close); };
  }, [open]);
  return (
    <div className="facet" ref={ref}>
      <button className={`btn small ${value.length ? "on" : ""}`} aria-haspopup="true" aria-expanded={open} onClick={() => setOpen(!open)}>
        <ListFilter aria-hidden="true" />{label}{value.length ? ` · ${value.length}` : ""}
      </button>
      {open && (
        <div className={`facet-pop ${align ?? ""}`} role="group" aria-label={`Filter by ${label}`}>
          {options.map((o) => (
            <label key={o.v}><input type="checkbox" checked={value.includes(o.v)}
              onChange={() => onChange(value.includes(o.v) ? value.filter((x) => x !== o.v) : [...value, o.v])} />{o.label}<span className="n">{o.n}</span></label>
          ))}
          {value.length > 0 && <button className="btn small ghost clear" onClick={() => onChange([])}>Clear</button>}
        </div>
      )}
    </div>
  );
}

const OPTIONAL_COLS: [string, string][] = [["location", "Location"], ["salary", "Salary"], ["posted", "Posted"], ["reqs", "Requirements"], ["sources", "Sources"]];

export function JobsTable({ jobs, threshold, onOpen, bulk, toolbarExtra }: {
  jobs: ScoredJob[]; threshold: number; onOpen: (j: ScoredJob) => void; bulk: BulkActions; toolbarExtra?: ReactNode;
}) {
  const [params, setParams] = useSearchParams();
  const setParam = (k: string, v: string | null) => setParams((p) => { const n = new URLSearchParams(p); if (!v) n.delete(k); else n.set(k, v); return n; }, { replace: true });
  const q = params.get("q") ?? "";
  const status = (params.get("st") ?? "").split(",").filter(Boolean);
  const sources = (params.get("src") ?? "").split(",").filter(Boolean);
  const setSources = (v: string[]) => setParam("src", v.join(",") || null);
  const [work, setWork] = useState<string[]>([]);
  const [verified, setVerified] = useState<string[]>([]);
  const [sorting, setSorting] = useState<SortingState>(() => {
    const s = params.get("sort");
    return s ? [{ id: s.split(".")[0], desc: s.endsWith(".desc") }] : [{ id: "score", desc: true }];
  });
  const [visibility, setVisibility] = useState<VisibilityState>(() => {
    try { return JSON.parse(localStorage.getItem("cvm.cols") || "{}"); } catch { return {}; }
  });
  const [compact, setCompact] = useState(() => { try { return localStorage.getItem("cvm.density") === "compact"; } catch { return false; } });
  const [selection, setSelection] = useState<RowSelectionState>({});
  const [cursor, setCursor] = useState(-1);
  const [colsOpen, setColsOpen] = useState(false);
  const search = useRef<HTMLInputElement>(null);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => { try { localStorage.setItem("cvm.cols", JSON.stringify(visibility)); } catch { /* blocked */ } }, [visibility]);
  useEffect(() => { try { localStorage.setItem("cvm.density", compact ? "compact" : ""); } catch { /* blocked */ } }, [compact]);
  useEffect(() => { const s = sorting[0]; setParam("sort", s && !(s.id === "score" && s.desc) ? `${s.id}.${s.desc ? "desc" : "asc"}` : null); }, [sorting]);  // eslint-disable-line react-hooks/exhaustive-deps

  const facetCounts = useMemo(() => {
    const c = { status: {} as Record<string, number>, source: {} as Record<string, number>, work: {} as Record<string, number>, ver: { yes: 0, no: 0 } };
    for (const j of jobs) {
      const st = statusOf(j, threshold); c.status[st] = (c.status[st] || 0) + 1;
      c.source[j.source] = (c.source[j.source] || 0) + 1;
      const w = workplace(j); c.work[w] = (c.work[w] || 0) + 1;
      c.ver[j.deep ? "yes" : "no"]++;
    }
    return c;
  }, [jobs, threshold]);

  const rows = useMemo(() => {
    const f = q.trim().toLowerCase();
    return jobs.filter((j) => (!status.length || status.includes(statusOf(j, threshold)))
      && (!sources.length || sources.includes(j.source))
      && (!work.length || work.includes(workplace(j)))
      && (!verified.length || verified.includes(j.deep ? "yes" : "no"))
      && (!f || `${j.title} ${j.company} ${j.location} ${j.matched_skills.join(" ")}`.toLowerCase().includes(f)));
  }, [jobs, q, status.join(), sources.join(), work, verified, threshold]);  // eslint-disable-line react-hooks/exhaustive-deps

  const columns = useMemo<ColumnDef<ScoredJob>[]>(() => [
    {
      id: "select", enableSorting: false,
      header: ({ table }) => <input type="checkbox" aria-label="Select all shown jobs" checked={table.getIsAllRowsSelected()}
        ref={(el) => { if (el) el.indeterminate = table.getIsSomeRowsSelected(); }} onChange={table.getToggleAllRowsSelectedHandler()} />,
      cell: ({ row }) => <input type="checkbox" aria-label={`Select ${row.original.title}`} checked={row.getIsSelected()}
        onClick={(e) => e.stopPropagation()} onChange={row.getToggleSelectedHandler()} />,
    },
    {
      id: "score", accessorKey: "score", header: "Match", sortDescFirst: true,
      cell: ({ row: { original: j } }) => (
        <span className={`scorebar ${tone(j.score, threshold)}`} title={j.deep ? `Rules ${j.deep.det_score}% → ${j.score}% after AI verification` : undefined}>
          <span className="bar-t"><i style={{ width: `${j.score}%` }} /></span><b>{j.score}%</b>
        </span>),
    },
    {
      id: "title", accessorFn: (j) => j.title.toLowerCase(), header: "Role",
      cell: ({ row: { original: j } }) => (
        <button className="r-head" onClick={(e) => { e.stopPropagation(); onOpen(j); }}>
          <span className="t-title">{j.title}</span><span className="t-sub">{j.company || "—"}</span>
        </button>),
    },
    {
      id: "status", accessorFn: (j) => ({ qualified: 2, gate: 1, below: 0 })[statusOf(j, threshold)], header: "Status", sortDescFirst: true,
      cell: ({ row: { original: j } }) => {
        const st = statusOf(j, threshold);
        return (
          <span className="t-tags">
            <span className={`tag ${st === "qualified" ? "q" : "nq"}`}>{st === "qualified" ? "Qualified" : st === "gate" ? "Gate" : "Below"}</span>
            {j.gates_failed?.slice(0, 2).map((g) => <span key={g} className="tag gate" title={j.gates?.find((x) => x.label === g)?.reason}>✕ {g}</span>)}
            {j.deep && <span className="tag ai" title={`${j.deep.verified} verified AI judgement(s)`}><ShieldCheck aria-hidden="true" />AI-verified</span>}
            {j.confidence === "low" && <span className="pill" title="Little description text; rough estimate">rough</span>}
          </span>);
      },
    },
    { id: "location", accessorKey: "location", header: "Location", cell: ({ row: { original: j } }) => <span className="muted-cell">{j.location || (j.remote ? "Remote" : "—")}</span> },
    { id: "salary", accessorKey: "salary", header: "Salary", cell: ({ getValue }) => <span className="muted-cell">{(getValue() as string) || "—"}</span> },
    { id: "posted", accessorFn: (j) => Date.parse(j.posted) || 0, header: "Posted", sortDescFirst: true, cell: ({ row: { original: j } }) => <span className="muted-cell">{relTime(j.posted) || "—"}</span> },
    {
      id: "reqs", accessorFn: (j) => (j.requirements.length ? j.requirements_met / j.requirements.length : -1), header: "Reqs met", sortDescFirst: true,
      cell: ({ row: { original: j } }) => <span className="muted-cell">{j.requirements.length ? `${j.requirements_met}/${j.requirements.length}` : "—"}</span>,
    },
    { id: "sources", accessorFn: (j) => j.source, header: "Source", cell: ({ row: { original: j } }) => <span className="badges"><SourceBadges sources={j.sources} /></span> },
  ], [threshold, onOpen]);

  const table = useReactTable({
    data: rows, columns, getRowId: (j) => j.id,
    state: { sorting, columnVisibility: visibility, rowSelection: selection },
    onSortingChange: setSorting, onColumnVisibilityChange: setVisibility, onRowSelectionChange: setSelection,
    getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel(), enableRowSelection: true,
  });
  const visibleRows = table.getRowModel().rows;
  const selectedJobs = jobs.filter((j) => selection[j.id]);
  const virtual = visibleRows.length > 120;
  const virt = useVirtualizer({ count: visibleRows.length, getScrollElement: () => scroller.current, estimateSize: () => (compact ? 36 : 46), overscan: 12, enabled: virtual });
  const items = virtual ? virt.getVirtualItems() : null;
  const padTop = items && items.length ? items[0].start : 0;
  const padBottom = items && items.length ? virt.getTotalSize() - items[items.length - 1].end : 0;
  const shown = items ? items.map((i) => visibleRows[i.index]) : visibleRows;
  const pos = useMemo(() => new Map(visibleRows.map((r, i) => [r.id, i])), [visibleRows]);   // on-screen order (row.index is data order)

  // keyboard: j/k move, Enter opens, x selects, / searches, Esc clears the selection
  const latest = useRef({ visibleRows, cursor, onOpen });
  latest.current = { visibleRows, cursor, onOpen };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e) || e.metaKey || e.ctrlKey || e.altKey || document.querySelector(".overlay, .cmdk-overlay")) return;
      const { visibleRows: vr, cursor: c, onOpen: open } = latest.current;
      if (e.key === "/") { e.preventDefault(); search.current?.focus(); return; }
      if (e.key === "j") { e.preventDefault(); setCursor(Math.min(vr.length - 1, c + 1)); }
      else if (e.key === "k") { e.preventDefault(); setCursor(Math.max(0, c - 1)); }
      else if (e.key === "Enter" && c >= 0 && vr[c]) { e.preventDefault(); open(vr[c].original); }
      else if (e.key === "x" && c >= 0 && vr[c]) { e.preventDefault(); vr[c].toggleSelected(); }
      else if (e.key === "Escape") setSelection({});
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => {
    if (cursor < 0) return;
    if (virtual) virt.scrollToIndex(cursor, { align: "auto" });
    else scroller.current?.querySelector<HTMLElement>(`tr[data-index="${cursor}"]`)?.scrollIntoView({ block: "nearest" });
  }, [cursor]);  // eslint-disable-line react-hooks/exhaustive-deps

  const filtersOn = status.length + sources.length + work.length + verified.length > 0 || q;
  const ncols = table.getVisibleLeafColumns().length;
  return (
    <div className="card flush">
      <div className="dt-toolbar">
        <div className="search"><Search aria-hidden="true" />
          <input ref={search} type="search" placeholder="Filter by title, company, skill…  ( / )" aria-label="Search jobs" value={q} onChange={(e) => setParam("q", e.target.value || null)} />
        </div>
        <Facet label="Status" value={status} onChange={(v) => setParam("st", v.join(",") || null)}
          options={[["qualified", "Qualified"], ["gate", "Fails a hard requirement"], ["below", "Below your bar"]].map(([v, l]) => ({ v, label: l, n: facetCounts.status[v] || 0 }))} />
        <Facet label="Source" value={sources} onChange={setSources}
          options={Object.entries(facetCounts.source).sort((a, b) => b[1] - a[1]).map(([v, n]) => ({ v, label: sourceName(v), n }))} />
        <Facet label="Workplace" value={work} onChange={setWork}
          options={["remote", "on-site", "unknown"].filter((v) => facetCounts.work[v]).map((v) => ({ v, label: v[0].toUpperCase() + v.slice(1), n: facetCounts.work[v] }))} />
        <Facet label="AI-verified" value={verified} onChange={setVerified}
          options={[{ v: "yes", label: "Verified", n: facetCounts.ver.yes }, { v: "no", label: "Not verified", n: facetCounts.ver.no }]} />
        {filtersOn && <button className="btn small ghost" onClick={() => { setParam("st", null); setParam("q", null); setSources([]); setWork([]); setVerified([]); }}><X aria-hidden="true" />Reset</button>}
        <span className="spacer" />
        {toolbarExtra}
        <span className="dt-meta" aria-live="polite">{rows.length} of {jobs.length}</span>
        <div className="facet">
          <button className="icon-btn" aria-label="Columns" title="Columns" aria-expanded={colsOpen} onClick={() => setColsOpen(!colsOpen)}><Columns3 /></button>
          {colsOpen && (
            <div className="facet-pop right" onMouseLeave={() => setColsOpen(false)}>
              {OPTIONAL_COLS.map(([id, label]) => (
                <label key={id}><input type="checkbox" checked={visibility[id] !== false} onChange={(e) => setVisibility({ ...visibility, [id]: e.target.checked })} />{label}</label>
              ))}
            </div>
          )}
        </div>
        <button className="icon-btn" onClick={() => setCompact(!compact)} aria-pressed={compact} aria-label="Toggle row density" title={compact ? "Comfortable rows" : "Compact rows"}>{compact ? <Rows2 /> : <Rows3 />}</button>
      </div>
      <div className="dt-wrap" ref={scroller}>
        <table className={`dt ${compact ? "compact" : ""}`} aria-rowcount={visibleRows.length}>
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>{hg.headers.map((h) => {
                const sorted = h.column.getIsSorted();
                return (
                  <th key={h.id} className={h.column.id === "select" ? "sel" : undefined} aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : undefined}>
                    {h.column.getCanSort() ? (
                      <button onClick={h.column.getToggleSortingHandler()}>{flexRender(h.column.columnDef.header, h.getContext())}
                        {sorted === "asc" ? <ArrowUp aria-hidden="true" /> : sorted === "desc" ? <ArrowDown aria-hidden="true" /> : <ArrowUpDown aria-hidden="true" style={{ opacity: .4 }} />}</button>
                    ) : flexRender(h.column.columnDef.header, h.getContext())}
                  </th>);
              })}</tr>
            ))}
          </thead>
          <tbody>
            {padTop > 0 && <tr aria-hidden="true"><td colSpan={ncols} style={{ height: padTop, padding: 0, border: 0 }} /></tr>}
            {shown.map((row) => (
              <tr key={row.id} data-index={pos.get(row.id)} className={`${row.getIsSelected() ? "sel" : ""} ${pos.get(row.id) === cursor ? "cursor" : ""}`}
                onClick={() => { setCursor(pos.get(row.id) ?? -1); onOpen(row.original); }}>
                {row.getVisibleCells().map((c) => <td key={c.id} className={c.column.id === "select" ? "sel" : undefined}>{flexRender(c.column.columnDef.cell, c.getContext())}</td>)}
              </tr>
            ))}
            {padBottom > 0 && <tr aria-hidden="true"><td colSpan={ncols} style={{ height: padBottom, padding: 0, border: 0 }} /></tr>}
          </tbody>
        </table>
        {rows.length === 0 && <div className="dt-empty">No jobs match these filters.</div>}
      </div>
      {selectedJobs.length > 0 && (
        <div className="bulkbar" role="toolbar" aria-label="Actions for selected jobs">
          <span>{selectedJobs.length} selected</span>
          <button className="btn small primary" onClick={() => bulk.verify(selectedJobs.map((j) => j.id))} title={bulk.verifyHint?.(selectedJobs.length)}>
            <ShieldCheck aria-hidden="true" />Deep verify{bulk.verifyHint ? <small className="est">{bulk.verifyHint(selectedJobs.length)}</small> : null}</button>
          <button className="btn small" onClick={() => bulk.save(selectedJobs)}><Bookmark aria-hidden="true" />Save</button>
          <button className="btn small" disabled={selectedJobs.length < 2 || selectedJobs.length > 4} title="Compare 2–4 jobs"
            onClick={() => bulk.compare(selectedJobs.map((j) => j.id))}><GitCompareArrows aria-hidden="true" />Compare</button>
          <button className="btn small" onClick={() => bulk.exportCsv(selectedJobs)}><Download aria-hidden="true" />CSV</button>
          <button className="icon-btn" aria-label="Clear selection" onClick={() => setSelection({})} style={{ color: "inherit" }}><X /></button>
        </div>
      )}
    </div>
  );
}

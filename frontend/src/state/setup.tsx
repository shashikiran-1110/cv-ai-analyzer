import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { SearchParams } from "../types";
import { EMPTY_RESUME, type ResumeState } from "../components/ResumeCard";
import { DEFAULT_SOURCES, type SourceConfig } from "../components/SourcesPicker";

export interface Options { threshold: number; wantAi: boolean; review: boolean; hours: number; autoDeep: number }
export const DEFAULT_PARAMS: SearchParams = { title: "", location: "", count: 40, time_range: "week", experience: [], job_types: [], workplace: [], sort: "recent", strict: true };
const DEFAULT_OPTS: Options = { threshold: 60, wantAi: true, review: false, hours: 72, autoDeep: 0 };
const KEY = "cvm.setup.v2";

interface Setup {
  resume: ResumeState; setResume: (r: ResumeState) => void;
  params: SearchParams; setParams: (p: SearchParams) => void;
  sources: SourceConfig; setSources: (s: SourceConfig) => void;
  opts: Options; setOpts: (o: Options) => void;
  reset: () => void;
}
const Ctx = createContext<Setup | null>(null);
export const useSetup = () => { const c = useContext(Ctx); if (!c) throw new Error("SetupProvider missing"); return c; };

/** Setup survives reloads (sessionStorage). Files are never stored; the server keeps the resume by id. */
function load() {
  try { return JSON.parse(sessionStorage.getItem(KEY) || "{}"); } catch { return {}; }
}

export function SetupProvider({ children }: { children: ReactNode }) {
  const saved = useMemo(load, []);
  const [resume, setResume] = useState<ResumeState>({ ...EMPTY_RESUME, ...(saved.resume || {}), file: null });
  const [params, setParams] = useState<SearchParams>({ ...DEFAULT_PARAMS, ...(saved.params || {}) });
  const [sources, setSources] = useState<SourceConfig>({ ...DEFAULT_SOURCES, ...(saved.sources || {}) });
  const [opts, setOpts] = useState<Options>({ ...DEFAULT_OPTS, ...(saved.opts || {}) });
  useEffect(() => {
    try {
      const { file, ...r } = resume; void file;
      sessionStorage.setItem(KEY, JSON.stringify({ resume: r, params, sources, opts }));
    } catch { /* storage full or blocked */ }
  }, [resume, params, sources, opts]);
  const reset = () => {
    try { sessionStorage.removeItem(KEY); } catch { /* blocked */ }
    setResume(EMPTY_RESUME); setParams(DEFAULT_PARAMS); setSources(DEFAULT_SOURCES); setOpts(DEFAULT_OPTS);
  };
  return <Ctx.Provider value={{ resume, setResume, params, setParams, sources, setSources, opts, setOpts, reset }}>{children}</Ctx.Provider>;
}

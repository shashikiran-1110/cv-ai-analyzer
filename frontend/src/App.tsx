import { useCallback, useEffect, useState } from "react";
import { AiProvider, useAi } from "./ai";
import { api, SERVER_DOWN } from "./api";
import { AiSettingsModal } from "./components/AiSettingsModal";
import { DiagnoseModal } from "./components/DiagnoseModal";
import { Header } from "./components/Header";
import { JobsStep } from "./components/JobsStep";
import { ReportStep } from "./components/ReportStep";
import { EMPTY_RESUME, type ResumeState } from "./components/ResumeCard";
import { DEFAULT_PARAMS, SetupStep, type Options } from "./components/SetupStep";
import { DEFAULT_SOURCES, type SourceConfig } from "./components/SourcesPicker";
import type { Analysis, SearchParams, SearchStatus } from "./types";

function Shell() {
  const ai = useAi();
  const [step, setStep] = useState(1);
  const [maxStep, setMaxStep] = useState(1);
  const [resume, setResume] = useState<ResumeState>(EMPTY_RESUME);
  const [params, setParams] = useState<SearchParams>(DEFAULT_PARAMS);
  const [sources, setSources] = useState<SourceConfig>(DEFAULT_SOURCES);
  const [opts, setOpts] = useState<Options>({ threshold: 60, wantAi: true, review: false, hours: 72 });
  const [search, setSearch] = useState<{ id: string; status: SearchStatus } | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [diag, setDiag] = useState(false);
  const [notes, setNotes] = useState<string[]>([]);
  const [serverDown, setServerDown] = useState(false);

  useEffect(() => {
    const check = () => api("/api/health").then(() => setServerDown(false)).catch(() => setServerDown(true));
    void check();
    const t = setInterval(check, 15000);
    return () => clearInterval(t);
  }, []);

  const go = (n: number) => { setStep(n); setMaxStep((m) => Math.max(m, n)); window.scrollTo({ top: 0, behavior: "smooth" }); };

  const analyze = useCallback(async (searchId: string, jobIds: string[], onStage: (s: string) => void, sourceNotes: string[] = []) => {
    const aiOn = opts.wantAi && ai.usable;
    onStage(aiOn ? "ai" : "analyzing");
    const fd = new FormData();
    fd.append("search_id", searchId);
    if (resume.mode === "pdf" && resume.file) fd.append("resume", resume.file); else fd.append("resume_text", resume.text);
    fd.append("threshold", String(opts.threshold));
    fd.append("use_ai", aiOn ? "true" : "false");
    fd.append("job_ids", JSON.stringify(jobIds));
    fd.append("extra_skills", JSON.stringify(resume.extra));
    const a = await api<Analysis>("/api/analyze", { method: "POST", body: fd, headers: aiOn ? ai.headers : {} });
    setAnalysis(a);
    setNotes(sourceNotes);
    setMaxStep(3);
    go(3);
  }, [opts, ai, resume]);

  return (
    <>
      <Header step={step} maxStep={maxStep} go={go} onDiagnose={() => setDiag(true)} />
      {serverDown && <div className="banner" role="alert">{SERVER_DOWN} <button className="link" onClick={() => setDiag(true)}>Details</button></div>}
      <main className="wrap">
        <div hidden={step !== 1}>
          <SetupStep resume={resume} setResume={setResume} params={params} setParams={setParams} sources={sources} setSources={setSources}
            opts={opts} setOpts={setOpts} analyze={analyze} openDiagnose={() => setDiag(true)}
            onReview={(id, s) => { setSearch({ id, status: s }); setMaxStep(2); go(2); }} />
        </div>
        {step === 2 && search && <JobsStep search={search.status} searchId={search.id} onBack={() => go(1)} analyze={analyze} />}
        {step === 3 && analysis && <ReportStep key={analysis.analysis_id} initial={analysis} initialThreshold={opts.threshold} notes={notes} onRestart={() => go(1)} />}
      </main>
      <footer className="wrap foot">Scores are an automated, explainable estimate (skills, requirements, role, experience, semantic overlap), not a hiring decision. Use them to prioritise and to spot gaps.</footer>
      {ai.modalOpen && <AiSettingsModal />}
      {diag && <DiagnoseModal onClose={() => setDiag(false)} />}
    </>
  );
}

export default function App() {
  return <AiProvider><Shell /></AiProvider>;
}

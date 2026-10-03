import { useState } from "react";
import { AiProvider, useAi } from "./ai";
import { AiSettingsModal } from "./components/AiSettingsModal";
import { Header } from "./components/Header";
import { JobsStep } from "./components/JobsStep";
import { ReportStep } from "./components/ReportStep";
import { ResumeStep } from "./components/ResumeStep";
import { SearchStep } from "./components/SearchStep";
import type { Analysis, JobSummary, SearchParams, SearchQuery } from "./types";

function Shell() {
  const ai = useAi();
  const [step, setStep] = useState(1);
  const [maxStep, setMaxStep] = useState(1);
  const [searchId, setSearchId] = useState("");
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [query, setQuery] = useState<SearchQuery | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [threshold, setThreshold] = useState(ai.config?.default_threshold ?? 60);
  const [prefill, setPrefill] = useState<SearchParams | null>(null);

  const go = (n: number) => { setStep(n); setMaxStep((m) => Math.max(m, n)); window.scrollTo({ top: 0, behavior: "smooth" }); };

  return (
    <>
      <Header step={step} maxStep={maxStep} go={go} />
      <main className="wrap">
        {step === 1 && (
          <SearchStep initial={prefill} onDone={(id, j, q) => {
            setSearchId(id); setJobs(j); setQuery(q); setSelected(new Set(j.map((x) => x.id))); setAnalysis(null);
            setPrefill({ title: q.title, location: q.location, count: q.count, time_range: q.time_range, experience: q.experience, job_types: q.job_types, workplace: q.workplace, sort: q.sort });
            setMaxStep(2); go(2);
          }} />
        )}
        {step === 2 && <JobsStep jobs={jobs} query={query} selected={selected} setSelected={setSelected} onBack={() => go(1)} onNext={() => go(3)} />}
        {step === 3 && (
          <ResumeStep searchId={searchId} jobIds={[...selected]} defaultThreshold={threshold} onBack={() => go(2)}
            onDone={(a, t) => { setAnalysis(a); setThreshold(t); go(4); }} />
        )}
        {step === 4 && analysis && <ReportStep key={analysis.analysis_id} initial={analysis} initialThreshold={threshold} onRestart={() => go(1)} onResume={() => go(3)} />}
      </main>
      <footer className="wrap foot">Scores are an automated estimate of skill, role and experience overlap, not a hiring decision. Use them to prioritise and to spot gaps.</footer>
      {ai.modalOpen && <AiSettingsModal />}
    </>
  );
}

export default function App() {
  return <AiProvider><Shell /></AiProvider>;
}

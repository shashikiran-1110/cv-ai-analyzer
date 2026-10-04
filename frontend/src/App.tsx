import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useState } from "react";
import { BrowserRouter, Link, Route, Routes, useLocation } from "react-router-dom";
import { AiProvider, useAi } from "./ai";
import { api, SERVER_DOWN } from "./api";
import { AiSettingsModal } from "./components/AiSettingsModal";
import { DiagnoseModal } from "./components/DiagnoseModal";
import { ClearSession } from "./components/shell/ClearSession";
import { CommandPalette } from "./components/shell/CommandPalette";
import { ErrorBoundary } from "./components/shell/ErrorBoundary";
import { ShellProvider, useShell } from "./components/shell/ShellProvider";
import { ShortcutsHelp } from "./components/shell/ShortcutsHelp";
import { Sidebar } from "./components/shell/Sidebar";
import { TopBar } from "./components/shell/TopBar";
import { Skeleton } from "./components/Skeleton";
import { SetupStep } from "./components/SetupStep";
import { ToastProvider } from "./components/Toast";
import { SearchPage } from "./pages/SearchPage";
import { SetupProvider } from "./state/setup";

const AnalysisPage = lazy(() => import("./pages/AnalysisPage").then((m) => ({ default: m.AnalysisPage })));
const JobPage = lazy(() => import("./pages/JobPage").then((m) => ({ default: m.JobPage })));
const ComparePage = lazy(() => import("./pages/ComparePage").then((m) => ({ default: m.ComparePage })));
const ReportsPage = lazy(() => import("./pages/ReportsPage").then((m) => ({ default: m.ReportsPage })));
const ProfilePage = lazy(() => import("./pages/ProfilePage").then((m) => ({ default: m.ProfilePage })));
const SettingsPage = lazy(() => import("./pages/SettingsPage").then((m) => ({ default: m.SettingsPage })));
const TailorPage = lazy(() => import("./pages/TailorPage").then((m) => ({ default: m.TailorPage })));
const InterviewPage = lazy(() => import("./pages/InterviewPage").then((m) => ({ default: m.InterviewPage })));
const TrackerPage = lazy(() => import("./pages/TrackerPage").then((m) => ({ default: m.TrackerPage })));
const WatchesPage = lazy(() => import("./pages/WatchesPage").then((m) => ({ default: m.WatchesPage })));
const MarketPage = lazy(() => import("./pages/MarketPage").then((m) => ({ default: m.MarketPage })));
const EvalStudioPage = lazy(() => import("./pages/EvalStudioPage").then((m) => ({ default: m.EvalStudioPage })));
const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } });

function Shell() {
  const ai = useAi();
  const shell = useShell();
  const loc = useLocation();
  const [serverDown, setServerDown] = useState(false);

  useEffect(() => {
    const check = () => api("/api/health").then(() => setServerDown(false)).catch(() => setServerDown(true));
    void check();
    const t = setInterval(check, 15000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => { window.scrollTo({ top: 0 }); }, [loc.pathname]);
  const openDiag = () => shell.setDiag(true);

  return (
    <div className={`app ${shell.collapsed ? "collapsed" : ""} ${shell.navOpen ? "nav-open" : ""}`}>
      <Sidebar />
      <div className="scrim" onClick={() => shell.setNavOpen(false)} aria-hidden="true" />
      <div className="app-main">
        <TopBar serverDown={serverDown} />
        {serverDown && <div className="banner" role="alert">{SERVER_DOWN} <button className="link" onClick={openDiag}>Details</button></div>}
        <main className="wrap" id="main">
          <div key={loc.pathname} className="route">
            <ErrorBoundary onClearSession={() => shell.setClearOpen(true)}>
            <Suspense fallback={<Skeleton rows={6} />}>
              <Routes location={loc}>
                <Route path="/" element={<SetupStep openDiagnose={openDiag} />} />
                <Route path="/search/:sid" element={<SearchPage openDiagnose={openDiag} />} />
                <Route path="/analysis/:aid" element={<AnalysisPage />} />
                <Route path="/analysis/:aid/job/:jobId" element={<JobPage />} />
                <Route path="/analysis/:aid/compare" element={<ComparePage />} />
                <Route path="/analysis/:aid/tailor/:jobId" element={<TailorPage />} />
                <Route path="/analysis/:aid/interview/:jobId" element={<InterviewPage />} />
                <Route path="/reports" element={<ReportsPage />} />
                <Route path="/profile/:rid" element={<ProfilePage />} />
                <Route path="/settings" element={<SettingsPage />} />
                <Route path="/tracker" element={<TrackerPage />} />
                <Route path="/watches" element={<WatchesPage />} />
                <Route path="/market" element={<MarketPage />} />
                <Route path="/eval" element={<EvalStudioPage />} />
                <Route path="*" element={<section className="empty-state"><h1>Page not found</h1><p className="muted">That link doesn't match any page.</p><Link className="btn" to="/">New search</Link></section>} />
              </Routes>
            </Suspense>
            </ErrorBoundary>
          </div>
        </main>
        <footer className="foot">Scores are an automated, explainable estimate (skills, requirements, role, experience, semantic overlap), not a hiring decision. Use them to prioritise and to spot gaps.</footer>
      </div>
      {ai.modalOpen && <AiSettingsModal />}
      {shell.diag && <DiagnoseModal onClose={() => shell.setDiag(false)} />}
      <CommandPalette />
      <ClearSession />
      <ShortcutsHelp />
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AiProvider><SetupProvider><ToastProvider><ShellProvider><Shell /></ShellProvider></ToastProvider></SetupProvider></AiProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

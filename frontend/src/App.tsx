import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { BrowserRouter, Link, Route, Routes, useLocation } from "react-router-dom";
import { AiProvider, useAi } from "./ai";
import { api, SERVER_DOWN } from "./api";
import { AiSettingsModal } from "./components/AiSettingsModal";
import { Background } from "./components/Background";
import { DiagnoseModal } from "./components/DiagnoseModal";
import { Header } from "./components/Header";
import { SetupStep } from "./components/SetupStep";
import { ToastProvider } from "./components/Toast";
import { AnalysisPage } from "./pages/AnalysisPage";
import { SearchPage } from "./pages/SearchPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SetupProvider } from "./state/setup";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } });

function Shell() {
  const ai = useAi();
  const loc = useLocation();
  const [diag, setDiag] = useState(false);
  const [serverDown, setServerDown] = useState(false);

  useEffect(() => {
    const check = () => api("/api/health").then(() => setServerDown(false)).catch(() => setServerDown(true));
    void check();
    const t = setInterval(check, 15000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => { window.scrollTo({ top: 0, behavior: "smooth" }); }, [loc.pathname]);

  return (
    <>
      <Background />
      <Header onDiagnose={() => setDiag(true)} />
      {serverDown && <div className="banner" role="alert">{SERVER_DOWN} <button className="link" onClick={() => setDiag(true)}>Details</button></div>}
      <main className="wrap">
        <div key={loc.pathname} className="route">
          <Routes location={loc}>
            <Route path="/" element={<SetupStep openDiagnose={() => setDiag(true)} />} />
            <Route path="/search/:sid" element={<SearchPage openDiagnose={() => setDiag(true)} />} />
            <Route path="/analysis/:aid" element={<AnalysisPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<section className="enter"><h1>Page not found</h1><Link className="btn" to="/">Go to setup</Link></section>} />
          </Routes>
        </div>
      </main>
      <footer className="wrap foot">Scores are an automated, explainable estimate (skills, requirements, role, experience, semantic overlap), not a hiring decision. Use them to prioritise and to spot gaps.</footer>
      {ai.modalOpen && <AiSettingsModal />}
      {diag && <DiagnoseModal onClose={() => setDiag(false)} />}
    </>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AiProvider><SetupProvider><ToastProvider><Shell /></ToastProvider></SetupProvider></AiProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

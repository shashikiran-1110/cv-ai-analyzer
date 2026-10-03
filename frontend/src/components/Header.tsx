import { useEffect, useState } from "react";
import { useAi } from "../ai";

const STEPS = ["Search", "Jobs", "Resume", "Report"];

export function Header({ step, maxStep, go }: { step: number; maxStep: number; go: (n: number) => void }) {
  const ai = useAi();
  const [theme, setTheme] = useState<string>(() => { try { return localStorage.getItem("cvm.theme") || "auto"; } catch { return "auto"; } });
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "auto") root.removeAttribute("data-theme"); else root.setAttribute("data-theme", theme);
    try { localStorage.setItem("cvm.theme", theme); } catch { /* ignore */ }
  }, [theme]);

  const label =
    ai.status === "checking" ? "Checking…"
    : ai.settings.key ? `${ai.settings.provider === "openai" ? "OpenAI" : "Anthropic"} · ${ai.settings.model}`
    : ai.serverAi ? `Server ${ai.serverAi} key`
    : "Add AI key";
  const dot = ai.status === "ok" ? "ok" : ai.status === "warn" ? "warn" : ai.status === "bad" ? "bad" : !ai.settings.key && ai.serverAi ? "ok" : "off";

  return (
    <header className="top">
      <div className="wrap top-in">
        <div className="brand"><span className="logo" aria-hidden="true">◎</span> CV Match Analyzer</div>
        <nav aria-label="Progress">
          <ol className="stepper">
            {STEPS.map((s, i) => {
              const n = i + 1, reachable = n <= maxStep && n !== step;
              return (
                <li key={s} className={n === step ? "active" : n < step ? "done" : ""} aria-current={n === step ? "step" : undefined}>
                  <button type="button" disabled={!reachable} onClick={() => go(n)}><span>{n}</span><em>{s}</em></button>
                </li>
              );
            })}
          </ol>
        </nav>
        <div className="top-actions">
          <button className="ai-chip" onClick={() => ai.openModal(true)} title={ai.message || "Configure AI"}>
            <i className={`dot-s ${dot}`} /> {label}
          </button>
          <button className="btn small" aria-label={`Theme: ${theme}. Click to change`} title="Switch theme"
            onClick={() => setTheme(theme === "auto" ? "dark" : theme === "dark" ? "light" : "auto")}>
            {theme === "dark" ? "Dark" : theme === "light" ? "Light" : "Auto"}
          </button>
        </div>
      </div>
    </header>
  );
}

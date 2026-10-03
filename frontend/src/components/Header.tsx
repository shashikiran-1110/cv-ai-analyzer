import { useEffect, useRef, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { useAi } from "../ai";

const STEPS = ["Setup", "Jobs", "Report"];

export function Header({ onDiagnose }: { onDiagnose: () => void }) {
  const ai = useAi();
  const path = useLocation().pathname;
  const step = path.startsWith("/analysis") ? 3 : path.startsWith("/search") ? 2 : path === "/" ? 1 : 0;
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
        <Link to="/" className="brand"><span className="logo" aria-hidden="true">◎</span> CV Match Analyzer</Link>
        <nav aria-label="Progress">
          <ol className="stepper">
            {STEPS.map((label, i) => {
              const n = i + 1;
              return (
                <li key={label} className={n === step ? "active" : n < step ? "done" : ""} aria-current={n === step ? "step" : undefined}>
                  {n === 1 ? <Link to="/"><span>{n}</span><em>{label}</em></Link> : <span className="st"><span>{n}</span><em>{label}</em></span>}
                </li>
              );
            })}
          </ol>
        </nav>
        <div className="top-actions">
          <Menu onDiagnose={onDiagnose} />
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

const LINKS: [string, string][] = [["/tracker", "Applications"], ["/watches", "Watches"], ["/market", "Market insights"], ["/settings", "Settings"]];

function Menu({ onDiagnose }: { onDiagnose: () => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const path = useLocation().pathname;
  useEffect(() => setOpen(false), [path]);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close); document.addEventListener("keydown", close);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", close); };
  }, [open]);
  return (
    <div className="menu" ref={ref}>
      <button className="btn small" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)} data-testid="menu">Menu ▾</button>
      {open && <div className="menu-pop" role="menu">
        {LINKS.map(([to, label]) => <NavLink key={to} role="menuitem" to={to}>{label}</NavLink>)}
        <button role="menuitem" onClick={() => { setOpen(false); onDiagnose(); }}>Connection check</button>
      </div>}
    </div>
  );
}

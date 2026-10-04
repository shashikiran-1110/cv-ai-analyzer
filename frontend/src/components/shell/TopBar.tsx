import { useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Menu, Monitor, Moon, Search, Sun, WifiOff } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { useAi } from "../../ai";
import type { Analysis } from "../../types";
import { useShell } from "./ShellProvider";

const TITLES: Record<string, string> = {
  reports: "Reports", tracker: "Applications", watches: "Watches", market: "Market", settings: "Settings", eval: "Eval Studio", profile: "Resume profile",
};

function useCrumbs(): { crumbs: { to?: string; label: string }[]; step: number } {
  const path = useLocation().pathname;
  const qc = useQueryClient();
  const parts = path.split("/").filter(Boolean);
  if (!parts.length) return { crumbs: [{ label: "New search" }], step: 1 };
  if (parts[0] === "search") return { crumbs: [{ to: "/", label: "New search" }, { label: "Jobs" }], step: 2 };
  if (parts[0] === "analysis") {
    const a = qc.getQueryData<Analysis>(["analysis", parts[1]]);
    const report = a ? `${a.query.title || "Report"}${a.query.location ? ` · ${a.query.location}` : ""}` : "Report";
    const base = [{ to: "/reports", label: "Reports" }, { to: parts.length > 2 ? `/analysis/${parts[1]}` : undefined, label: report }];
    if (parts[2] === "job") return { crumbs: [...base, { label: a?.jobs.find((j) => j.id === parts[3])?.title ?? "Job" }], step: 0 };
    if (parts[2] === "compare") return { crumbs: [...base, { label: "Compare" }], step: 0 };
    if (parts[2] === "tailor") return { crumbs: [...base, { label: "Tailor resume" }], step: 0 };
    if (parts[2] === "interview") return { crumbs: [...base, { label: "Interview practice" }], step: 0 };
    return { crumbs: base, step: 3 };
  }
  return { crumbs: [{ label: TITLES[parts[0]] ?? parts[0] }], step: 0 };
}

export function TopBar({ serverDown }: { serverDown: boolean }) {
  const ai = useAi();
  const shell = useShell();
  const { crumbs, step } = useCrumbs();
  const label = ai.status === "checking" ? "Checking…"
    : ai.settings.key ? `${ai.settings.provider === "openai" ? "OpenAI" : "Anthropic"} · ${ai.settings.model}`
    : ai.serverAi ? `Server ${ai.serverAi} key` : "Add AI key";
  const dot = ai.status === "ok" ? "ok" : ai.status === "warn" ? "warn" : ai.status === "bad" ? "bad" : !ai.settings.key && ai.serverAi ? "ok" : "off";
  const ThemeIcon = shell.theme === "dark" ? Moon : shell.theme === "light" ? Sun : Monitor;
  const mac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

  return (
    <header className="top">
      <button className="icon-btn nav-toggle" aria-label="Open navigation" aria-expanded={shell.navOpen} onClick={() => shell.setNavOpen(!shell.navOpen)}><Menu /></button>
      <nav className="crumbs" aria-label="Breadcrumb">
        {crumbs.map((c, i) => (
          <span key={i} style={{ display: "contents" }}>
            {i > 0 && <ChevronRight aria-hidden="true" />}
            {c.to && i < crumbs.length - 1 ? <Link to={c.to}>{c.label}</Link> : <b aria-current={i === crumbs.length - 1 ? "page" : undefined}>{c.label}</b>}
          </span>
        ))}
      </nav>
      {step > 0 && (
        <div className="flow" aria-label="Progress">
          {["Setup", "Jobs", "Report"].map((s, i) => <span key={s} className={i + 1 === step ? "on" : i + 1 < step ? "done" : ""} aria-current={i + 1 === step ? "step" : undefined}>{i + 1}. {s}</span>)}
        </div>
      )}
      <div className="top-actions">
        {serverDown && <button className="status-pill" onClick={() => shell.setDiag(true)} title="The API server isn't responding"><WifiOff size={13} aria-hidden="true" /> Offline</button>}
        <button className="cmdk-trigger" onClick={() => shell.setPalette(true)} aria-label="Search or run a command">
          <Search aria-hidden="true" /><span>Search or jump to…</span><span className="kbd">{mac ? "⌘K" : "Ctrl K"}</span>
        </button>
        <button className="ai-chip" onClick={() => ai.openModal(true)} title={ai.message || "Configure AI"}>
          <i className={`dot-s ${dot}`} aria-hidden="true" /><span className="ai-label">{label}</span>
        </button>
        <button className="icon-btn" onClick={shell.cycleTheme} aria-label={`Theme: ${shell.theme}. Click to change`} title={`Theme: ${shell.theme}`}><ThemeIcon /></button>
      </div>
    </header>
  );
}

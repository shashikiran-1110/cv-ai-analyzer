import { useQuery } from "@tanstack/react-query";
import { Command } from "cmdk";
import { Bot, Clock, FileText, Keyboard, Monitor, Moon, Plus, Sun, Wifi } from "lucide-react";
import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useAi } from "../../ai";
import { api } from "../../api";
import type { AnalysisListItem } from "../../types";
import { NAV, NAV_TOOLS } from "./Sidebar";
import { useShell, type Cmd } from "./ShellProvider";

const ago = (t: number) => {
  const s = Date.now() / 1000 - t;
  return s < 3600 ? `${Math.max(1, Math.round(s / 60))}m ago` : s < 86400 ? `${Math.round(s / 3600)}h ago` : `${Math.round(s / 86400)}d ago`;
};

export function CommandPalette() {
  const shell = useShell();
  const ai = useAi();
  const navigate = useNavigate();
  const box = useRef<HTMLDivElement>(null);
  const recent = useQuery({
    queryKey: ["analyses"], queryFn: () => api<AnalysisListItem[]>("/api/analyses"), enabled: shell.palette, staleTime: 30_000, retry: 0,
  });

  useEffect(() => {
    if (!shell.palette) return;
    const prev = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { e.preventDefault(); shell.setPalette(false); } };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); prev?.focus?.(); };
  }, [shell.palette]);  // eslint-disable-line react-hooks/exhaustive-deps

  if (!shell.palette) return null;
  const go = (fn: () => void) => () => { shell.setPalette(false); fn(); };
  const ThemeIcon = shell.theme === "dark" ? Moon : shell.theme === "light" ? Sun : Monitor;

  const groups: Record<string, Cmd[]> = {};
  for (const c of shell.commands) (groups[c.group] ??= []).push(c);

  return (
    <div className="cmdk-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) shell.setPalette(false); }}>
      <div className="cmdk" ref={box} role="dialog" aria-modal="true" aria-label="Command menu">
        <Command label="Command menu" loop>
          <Command.Input autoFocus placeholder="Type a command, page, or job…" />
          <Command.List>
            <Command.Empty>No results.</Command.Empty>
            {Object.entries(groups).map(([g, cmds]) => (
              <Command.Group key={g} heading={g}>
                {cmds.map((c) => (
                  <Command.Item key={c.id} value={`${c.label} ${c.id}`} keywords={c.keywords} disabled={c.disabled} onSelect={go(c.run)}>
                    {c.icon}<span>{c.label}</span>{c.right ?? (c.hint && <span className="hint">{c.hint}</span>)}
                  </Command.Item>
                ))}
              </Command.Group>
            ))}
            <Command.Group heading="Go to">
              <Command.Item value="New search" keywords={["setup", "home", "start"]} onSelect={go(() => navigate("/"))}><Plus /><span>New search</span></Command.Item>
              {[...NAV, ...NAV_TOOLS].map(({ to, label, icon: I }) => (
                <Command.Item key={to} value={label} onSelect={go(() => navigate(to))}><I /><span>{label}</span></Command.Item>
              ))}
            </Command.Group>
            {(recent.data?.length ?? 0) > 0 && (
              <Command.Group heading="Recent reports">
                {recent.data!.slice(0, 6).map((r) => (
                  <Command.Item key={r.analysis_id} value={`report ${r.title} ${r.location} ${r.analysis_id}`} onSelect={go(() => navigate(`/analysis/${r.analysis_id}`))}>
                    <FileText /><span>{r.title || "Report"}{r.location ? ` · ${r.location}` : ""}</span>
                    <span className="hint">{r.qualifying}/{r.job_count} · {ago(r.created_at)}</span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}
            <Command.Group heading="Preferences">
              <Command.Item value="Toggle theme" keywords={["dark", "light", "appearance"]} onSelect={() => shell.cycleTheme()}><ThemeIcon /><span>Theme: {shell.theme}</span><span className="hint">cycle</span></Command.Item>
              <Command.Item value="AI settings" keywords={["key", "openai", "anthropic", "model"]} onSelect={go(() => ai.openModal(true))}><Bot /><span>AI settings</span></Command.Item>
              <Command.Item value="Connection check" keywords={["diagnose", "network"]} onSelect={go(() => shell.setDiag(true))}><Wifi /><span>Connection check</span></Command.Item>
              <Command.Item value="Keyboard shortcuts" keywords={["help", "keys"]} onSelect={go(() => shell.setShortcuts(true))}><Keyboard /><span>Keyboard shortcuts</span><span className="hint">?</span></Command.Item>
              <Command.Item value="Reports history" onSelect={go(() => navigate("/reports"))}><Clock /><span>All reports</span></Command.Item>
            </Command.Group>
          </Command.List>
        </Command>
        <div className="cmdk-foot"><span><kbd>↑</kbd><kbd>↓</kbd> move</span><span><kbd>↵</kbd> open</span><span><kbd>esc</kbd> close</span></div>
      </div>
    </div>
  );
}

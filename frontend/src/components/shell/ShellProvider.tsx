import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

export type Theme = "auto" | "light" | "dark";
export interface Cmd {
  id: string; label: string; group: string; run: () => void;
  icon?: ReactNode; hint?: string; keywords?: string[]; right?: ReactNode; disabled?: boolean;
}

interface Shell {
  theme: Theme; setTheme: (t: Theme) => void; cycleTheme: () => void;
  palette: boolean; setPalette: (v: boolean) => void;
  shortcuts: boolean; setShortcuts: (v: boolean) => void;
  diag: boolean; setDiag: (v: boolean) => void;
  navOpen: boolean; setNavOpen: (v: boolean) => void;
  clearOpen: boolean; setClearOpen: (v: boolean) => void;
  collapsed: boolean; setCollapsed: (v: boolean) => void;
  commands: Cmd[]; register: (key: string, cmds: Cmd[]) => void; unregister: (key: string) => void;
}
const Ctx = createContext<Shell | null>(null);
export const useShell = () => { const c = useContext(Ctx); if (!c) throw new Error("ShellProvider missing"); return c; };

const read = (k: string, d: string) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } };
const write = (k: string, v: string) => { try { localStorage.setItem(k, v); } catch { /* storage blocked */ } };

/** Typing in a field must never trigger single-key shortcuts. */
export const isTyping = (e: KeyboardEvent) => {
  const t = e.target as HTMLElement | null;
  return !!t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
};

export function ShellProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => read("cvm.theme", "auto") as Theme);
  const [palette, setPalette] = useState(false);
  const [shortcuts, setShortcuts] = useState(false);
  const [diag, setDiag] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [clearOpen, setClearOpen] = useState(false);
  const [collapsed, setCollapsedState] = useState(() => read("cvm.side", "") === "collapsed");
  const [registry, setRegistry] = useState<Record<string, Cmd[]>>({});

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "auto") root.removeAttribute("data-theme"); else root.setAttribute("data-theme", theme);
    write("cvm.theme", theme);
  }, [theme]);
  const setTheme = useCallback((t: Theme) => setThemeState(t), []);
  const cycleTheme = useCallback(() => setThemeState((t) => (t === "auto" ? "light" : t === "light" ? "dark" : "auto")), []);
  const setCollapsed = useCallback((v: boolean) => { setCollapsedState(v); write("cvm.side", v ? "collapsed" : ""); }, []);
  const register = useCallback((key: string, cmds: Cmd[]) => setRegistry((r) => ({ ...r, [key]: cmds })), []);
  const unregister = useCallback((key: string) => setRegistry((r) => { const n = { ...r }; delete n[key]; return n; }), []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((p) => !p); return; }
      if (isTyping(e) || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "?") { e.preventDefault(); setShortcuts(true); }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const commands = useMemo(() => Object.values(registry).flat(), [registry]);
  const value = useMemo<Shell>(() => ({
    theme, setTheme, cycleTheme, palette, setPalette, shortcuts, setShortcuts, diag, setDiag,
    navOpen, setNavOpen, clearOpen, setClearOpen, collapsed, setCollapsed, commands, register, unregister,
  }), [theme, setTheme, cycleTheme, palette, shortcuts, diag, navOpen, clearOpen, collapsed, setCollapsed, commands, register, unregister]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** Pages add context-specific entries to the command palette while they're mounted. */
export function useRegisterCommands(key: string, cmds: Cmd[]) {
  const { register, unregister } = useShell();
  const latest = useRef(cmds);
  latest.current = cmds;
  // re-register when the visible set changes; `run` always calls the latest closure
  const sig = cmds.map((c) => `${c.id}|${c.label}|${c.hint ?? ""}|${c.disabled ? 1 : 0}`).join(";");
  useEffect(() => {
    register(key, latest.current.map((c) => ({ ...c, run: () => latest.current.find((x) => x.id === c.id)?.run() })));
  }, [key, sig, register]);
  useEffect(() => () => unregister(key), [key, unregister]);
}

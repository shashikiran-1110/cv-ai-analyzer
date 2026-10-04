import { Bell, Briefcase, ChartLine, Clock, FlaskConical, Keyboard, PanelLeft, Plus, ScanSearch, Settings, Wifi } from "lucide-react";
import { useEffect } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { useShell } from "./ShellProvider";

export const NAV = [
  { to: "/reports", label: "Reports", icon: Clock },
  { to: "/tracker", label: "Applications", icon: Briefcase },
  { to: "/watches", label: "Watches", icon: Bell },
  { to: "/market", label: "Market", icon: ChartLine },
] as const;
export const NAV_TOOLS = [
  { to: "/eval", label: "Eval Studio", icon: FlaskConical },
  { to: "/settings", label: "Settings", icon: Settings },
] as const;

export function Sidebar() {
  const shell = useShell();
  const path = useLocation().pathname;
  useEffect(() => shell.setNavOpen(false), [path]);  // eslint-disable-line react-hooks/exhaustive-deps
  const tip = (label: string) => (shell.collapsed ? label : undefined);
  return (
    <aside className="side" aria-label="Main navigation">
      <Link to="/" className="brand side-brand" title="CV Match Analyzer">
        <span className="logo-mark" aria-hidden="true"><ScanSearch /></span><span>CV Match</span>
      </Link>
      <Link to="/" className="btn new" title={tip("New search")}><Plus aria-hidden="true" /><span>New search</span></Link>
      <nav className="side-nav">
        {NAV.map(({ to, label, icon: I }) => (
          <NavLink key={to} to={to} className="nav-item" title={tip(label)}><I aria-hidden="true" /><span>{label}</span></NavLink>
        ))}
      </nav>
      <div className="side-label">Tools</div>
      <nav className="side-nav" aria-label="Tools">
        {NAV_TOOLS.map(({ to, label, icon: I }) => (
          <NavLink key={to} to={to} className="nav-item" title={tip(label)}><I aria-hidden="true" /><span>{label}</span></NavLink>
        ))}
      </nav>
      <div className="side-foot">
        <button className="nav-item" onClick={() => shell.setDiag(true)} title={tip("Connection check")}><Wifi aria-hidden="true" /><span>Connection check</span></button>
        <button className="nav-item" onClick={() => shell.setShortcuts(true)} title={tip("Keyboard shortcuts")}><Keyboard aria-hidden="true" /><span>Shortcuts</span></button>
        <button className="nav-item collapse-btn" onClick={() => shell.setCollapsed(!shell.collapsed)} aria-pressed={shell.collapsed}
          title={shell.collapsed ? "Expand sidebar" : undefined}><PanelLeft aria-hidden="true" /><span>Collapse</span></button>
      </div>
    </aside>
  );
}

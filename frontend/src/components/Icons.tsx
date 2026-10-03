const P = { width: 16, height: 16, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2.4, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true };
export const IconCheck = () => <svg {...P}><path d="M20 6 9 17l-5-5" /></svg>;
export const IconX = () => <svg {...P}><path d="M18 6 6 18M6 6l12 12" /></svg>;
export const IconWarn = () => <svg {...P}><path d="M12 9v4M12 17h.01" /><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /></svg>;
export const IconHalf = () => <svg {...P}><circle cx="12" cy="12" r="9" /><path d="M12 3v18" /></svg>;
export const IconLink = () => <svg {...P}><path d="M7 17 17 7M8 7h9v9" /></svg>;
export const IconShield = () => <svg {...P}><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /><path d="m9 12 2 2 4-4" /></svg>;
export const Spinner = () => <span className="spin" aria-hidden="true" />;

export function StatusIcon({ s }: { s: "met" | "partial" | "missing" | "ok" | "bad" | "running" | "warn" }) {
  if (s === "running") return <Spinner />;
  const cls = s === "met" || s === "ok" ? "good" : s === "partial" || s === "warn" ? "warn" : "bad";
  return <span className={`si ${cls}`}>{s === "met" || s === "ok" ? <IconCheck /> : s === "partial" ? <IconHalf /> : s === "warn" ? <IconWarn /> : <IconX />}</span>;
}

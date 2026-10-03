import type { ReactNode } from "react";

export const Alert = ({ kind = "error", children }: { kind?: "error" | "info" | "warn" | "ok"; children: ReactNode }) =>
  <div className={`alert ${kind}`} role={kind === "error" ? "alert" : "status"}>{children}</div>;

export const Meter = ({ value, tone = "brand" }: { value: number; tone?: "brand" | "warn" | "good" }) =>
  <div className="meter" aria-hidden="true"><i className={tone} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} /></div>;

export const Chip = ({ children, tone = "" }: { children: ReactNode; tone?: "ok" | "miss" | "pref" | "" }) =>
  <span className={`chip ${tone}`}>{children}</span>;

export function Chips({ label, items, tone }: { label: string; items: string[]; tone: "ok" | "miss" | "pref" }) {
  if (!items.length) return null;
  return <div><h4>{label}</h4><div className="chips">{items.map((s) => <Chip key={s} tone={tone}>{s}</Chip>)}</div></div>;
}

export function Gauge({ pct, label }: { pct: number; label: string }) {
  const C = 2 * Math.PI * 54;
  return (
    <div className="gauge" role="img" aria-label={label}>
      <svg viewBox="0 0 130 130">
        <circle className="g-track" cx="65" cy="65" r="54" fill="none" strokeWidth="12" />
        <circle className="g-fill" cx="65" cy="65" r="54" fill="none" strokeWidth="12" strokeLinecap="round"
          strokeDasharray={C} strokeDashoffset={C * (1 - pct / 100)} />
      </svg>
      <div className="g-label">{pct}%</div>
    </div>
  );
}

export const safeUrl = (u: string) => { try { const x = new URL(u); return /^https?:$/.test(x.protocol) ? x.href : "#"; } catch { return "#"; } };
export const scoreTone = (s: number, t: number) => (s >= t ? "hi" : s >= t - 20 ? "mid" : "lo");

import { ArrowUpRight, Check, Contrast, ShieldCheck, TriangleAlert, X } from "lucide-react";

export const IconCheck = () => <Check aria-hidden="true" />;
export const IconX = () => <X aria-hidden="true" />;
export const IconWarn = () => <TriangleAlert aria-hidden="true" />;
export const IconHalf = () => <Contrast aria-hidden="true" />;
export const IconLink = () => <ArrowUpRight aria-hidden="true" />;
export const IconShield = () => <ShieldCheck aria-hidden="true" />;
export const Spinner = () => <span className="spin" aria-hidden="true" />;

export function StatusIcon({ s }: { s: "met" | "partial" | "missing" | "ok" | "bad" | "running" | "warn" }) {
  if (s === "running") return <Spinner />;
  const cls = s === "met" || s === "ok" ? "good" : s === "partial" || s === "warn" ? "warn" : "bad";
  const label = s === "met" || s === "ok" ? "met" : s === "partial" ? "partial" : s === "warn" ? "warning" : "missing";
  return <span className={`si ${cls}`} role="img" aria-label={label}>{s === "met" || s === "ok" ? <IconCheck /> : s === "partial" ? <IconHalf /> : s === "warn" ? <IconWarn /> : <IconX />}</span>;
}

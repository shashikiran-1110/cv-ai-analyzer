/** Small inline-SVG charts (no chart library). Colors come from CSS tokens. */

export function ScoreHistogram({ scores, threshold, bins = 10 }: { scores: number[]; threshold: number; bins?: number }) {
  const W = 520, H = 140, pad = { l: 4, r: 4, t: 16, b: 18 };
  const counts = Array.from({ length: bins }, () => 0);
  scores.forEach((s) => { counts[Math.min(bins - 1, Math.floor((s / 100) * bins))]++; });
  const max = Math.max(1, ...counts);
  const bw = (W - pad.l - pad.r) / bins;
  const x = (v: number) => pad.l + (v / 100) * (W - pad.l - pad.r);
  const h = H - pad.t - pad.b;
  return (
    <div className="hist">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Score distribution: ${counts.map((c, i) => `${i * (100 / bins)}–${(i + 1) * (100 / bins)}: ${c}`).join(", ")}`}>
        {counts.map((c, i) => {
          const bh = (c / max) * h;
          const lo = i * (100 / bins);
          return (
            <g key={i}>
              <rect className={`h-bar ${lo >= threshold ? "q" : ""}`} x={pad.l + i * bw + 2} y={pad.t + h - bh} width={bw - 4} height={Math.max(bh, c ? 2 : 0)} rx={2} />
              {c > 0 && <text className="h-axis" x={pad.l + i * bw + bw / 2} y={pad.t + h - bh - 4} textAnchor="middle">{c}</text>}
            </g>
          );
        })}
        {[0, 20, 40, 60, 80, 100].map((v) => <text key={v} className="h-axis" x={x(v)} y={H - 4} textAnchor={v === 0 ? "start" : v === 100 ? "end" : "middle"}>{v}</text>)}
        <line className="h-thr" x1={x(threshold)} x2={x(threshold)} y1={pad.t - 6} y2={pad.t + h} />
        <text className="h-thr-label" x={x(threshold) + 4} y={pad.t - 6}>{threshold}% bar</text>
      </svg>
      <div className="legend-row"><span><i style={{ background: "var(--brand)" }} />at or above your bar</span><span><i style={{ background: "var(--surface-3)" }} />below</span></div>
    </div>
  );
}

export function HBars({ rows, total, tone = "brand", onPick, show = "pct" }: {
  rows: { label: string; value: number; hint?: string; sub?: number }[]; total: number; tone?: "brand" | "warn" | "good";
  onPick?: (label: string) => void; show?: "pct" | "count";
}) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div className="hbars">
      {rows.map((r) => {
        const body = <>
          <span>{r.label}</span>
          <div className="meter stacked" aria-hidden="true"><i className={tone} style={{ width: `${(r.value / max) * 100}%` }} />
            {r.sub !== undefined && <i className="good sub" style={{ width: `${(r.sub / max) * 100}%` }} />}</div>
          <em>{show === "count" ? (r.sub !== undefined ? `${r.sub}/${r.value}` : r.value) : total ? `${Math.round((r.value / total) * 100)}%` : r.value}</em>
        </>;
        return onPick
          ? <button type="button" className="hbar clickable" key={r.label} title={r.hint ?? `Show ${r.label} in the table`} onClick={() => onPick(r.label)}>{body}</button>
          : <div className="hbar" key={r.label} title={r.hint}>{body}</div>;
      })}
    </div>
  );
}

export function Sparkline({ values, label }: { values: number[]; label: string }) {
  if (values.length < 2) return null;
  const W = 120, H = 28, lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * W},${H - 3 - ((v - lo) / span) * (H - 6)}`);
  return <svg className="spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={label}><path d={`M${pts.join(" L")}`} /></svg>;
}

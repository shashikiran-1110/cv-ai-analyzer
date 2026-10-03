export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="card skeleton" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => <div key={i} className="sk-line" style={{ width: `${90 - i * 12}%` }} />)}
    </div>
  );
}

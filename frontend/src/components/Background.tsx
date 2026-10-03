/** Decorative animated background: soft drifting color fields (pure CSS, paused for reduced motion). */
export function Background() {
  return (
    <div className="bg-scene" aria-hidden="true">
      <span className="blob b1" /><span className="blob b2" /><span className="blob b3" /><span className="grain" />
    </div>
  );
}

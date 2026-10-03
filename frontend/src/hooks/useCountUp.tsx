import { useEffect, useRef, useState } from "react";

const reduce = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** Animate a number toward `target` (respects reduced-motion). */
export function useCountUp(target: number, ms = 700): number {
  const [v, setV] = useState(reduce() ? target : 0);
  const from = useRef(v);
  useEffect(() => {
    if (reduce()) { setV(target); return; }
    const start = performance.now(), a = from.current;
    let raf = 0;
    const tick = (t: number) => {
      const k = Math.min(1, (t - start) / ms), e = 1 - Math.pow(1 - k, 3);
      const val = Math.round(a + (target - a) * e);
      setV(val); from.current = val;
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return v;
}

export function CountUp({ value }: { value: number }) {
  return <>{useCountUp(value)}</>;
}

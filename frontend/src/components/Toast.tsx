import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

type Kind = "ok" | "error" | "info";
interface Toast { id: number; kind: Kind; text: string }
const Ctx = createContext<(text: string, kind?: Kind) => void>(() => {});
export const useToast = () => useContext(Ctx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((text: string, kind: Kind = "info") => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x.slice(-3), { id, kind, text }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), kind === "error" ? 7000 : 3500);
  }, []);
  return (
    <Ctx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => <div key={t.id} className={`toast ${t.kind}`}>{t.text}
          <button className="x" aria-label="Dismiss" onClick={() => setItems((x) => x.filter((y) => y.id !== t.id))}>×</button></div>)}
      </div>
    </Ctx.Provider>
  );
}

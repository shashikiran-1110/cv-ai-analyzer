import { X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

/** Dialog. `sheet` slides in from the right (job quick view); otherwise a centered modal. */
export function Modal({ title, onClose, children, wide, sheet, headActions, subtitle }: {
  title: string; onClose: () => void; children: ReactNode; wide?: boolean; sheet?: boolean; headActions?: ReactNode; subtitle?: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>(sheet ? "button,a[href]" : "input,textarea,select,button")?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { close.current(); return; }
      if (e.key !== "Tab" || !ref.current) return;            // keep focus inside the dialog
      const f = ref.current.querySelectorAll<HTMLElement>("a[href],button:not(:disabled),input,select,textarea,[tabindex='0']");
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => { document.removeEventListener("keydown", onKey); document.body.style.overflow = ""; prev?.focus?.(); };
  }, [sheet]);
  return (
    <div className={`overlay ${sheet ? "sheet" : ""}`} onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className={`modal ${wide ? "wide" : ""}`} role="dialog" aria-modal="true" aria-label={title} ref={ref}>
        <div className="modal-head">
          <div style={{ minWidth: 0 }}><h2>{title}</h2>{subtitle}</div>
          <div className="head-actions">{headActions}<button className="icon-btn" aria-label="Close" onClick={onClose}><X /></button></div>
        </div>
        {sheet ? <div className="modal-body">{children}</div> : children}
      </div>
    </div>
  );
}

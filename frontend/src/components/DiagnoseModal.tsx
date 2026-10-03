import { useEffect, useState } from "react";
import { useAi } from "../ai";
import { api } from "../api";
import type { Diagnosis } from "../types";
import { StatusIcon } from "./Icons";
import { Modal } from "./Modal";
import { Alert } from "./ui";

export function DiagnoseModal({ onClose }: { onClose: () => void }) {
  const ai = useAi();
  const [d, setD] = useState<Diagnosis | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(true);
  async function run() {
    setBusy(true); setErr("");
    try { setD(await api<Diagnosis>("/api/diagnose", { headers: ai.headers })); }
    catch (e) { setErr((e as Error).message); setD(null); }
    finally { setBusy(false); }
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { void run(); }, []);
  const checks = d ? Object.entries(d.checks) : [];
  const blocked = checks.filter(([, c]) => !c.ok);
  return (
    <Modal title="Connection check" onClose={onClose} wide>
      <p className="muted">Tests whether the app's server can reach each job source and AI provider. “Request failed” errors almost always mean one of these is blocked on the network the server runs on.</p>
      {err && <Alert>{err}</Alert>}
      {busy && <p className="muted">Checking… (up to ~10 seconds)</p>}
      {d && <>
        <ul className="checklist">
          <li><StatusIcon s="ok" /><b>App API server</b><span>{d.api.message}</span></li>
          {checks.map(([k, c]) => <li key={k}><StatusIcon s={c.ok ? "ok" : "bad"} /><b>{c.name}</b><span>{c.message}</span></li>)}
          <li><StatusIcon s={d.ai_key.ok ? "ok" : "warn"} /><b>Your AI key</b><span>{d.ai_key.message}</span></li>
        </ul>
        {blocked.length > 0 && (
          <Alert kind="warn">
            {blocked.length} host{blocked.length > 1 ? "s are" : " is"} unreachable from the server. If you're running in a sandbox or behind a corporate
            proxy, allow those domains in its network settings, or run the app on your own computer (<code>./run.sh</code>). Meanwhile you can use
            sources that work, <b>Paste jobs</b>, or <b>Sample jobs</b>.
          </Alert>
        )}
      </>}
      <div className="actions end"><button className="btn" onClick={run} disabled={busy}>Re-run check</button><button className="btn primary" onClick={onClose}>Done</button></div>
    </Modal>
  );
}

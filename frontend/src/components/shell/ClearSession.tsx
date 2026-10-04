import { useQueryClient } from "@tanstack/react-query";
import { Eraser } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAi } from "../../ai";
import { api } from "../../api";
import { useSetup } from "../../state/setup";
import { Modal } from "../Modal";
import { useToast } from "../Toast";
import { useShell } from "./ShellProvider";

/** Discard this tab's data: resume, search form, sources, options and every cached report in memory.
 *  Optionally also forget the AI key in this tab, or delete everything saved on the server for this browser. */
export function ClearSession() {
  const shell = useShell();
  const setup = useSetup();
  const ai = useAi();
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const [forgetKey, setForgetKey] = useState(false);
  const [server, setServer] = useState(false);
  const [busy, setBusy] = useState(false);
  if (!shell.clearOpen) return null;
  const close = () => { shell.setClearOpen(false); setServer(false); setForgetKey(false); };

  async function clear() {
    setBusy(true);
    try {
      if (server) await api("/api/me", { method: "DELETE" });
      setup.reset();
      try {
        for (const k of Object.keys(sessionStorage)) if (k.startsWith("cvm.") && (forgetKey || k !== "cvm.ai.key")) sessionStorage.removeItem(k);
      } catch { /* storage blocked */ }
      if (forgetKey) ai.clear();
      qc.clear();
      close();
      navigate("/");
      toast(server ? "Session cleared and your saved data deleted from the server." : "Session cleared. This tab starts fresh.", "ok");
    } catch (e) { toast((e as Error).message, "error"); }
    finally { setBusy(false); }
  }

  return (
    <Modal title="Clear session" onClose={close}>
      <p className="muted" style={{ fontSize: 13.5 }}>This discards everything this tab is holding: your resume and search form, sources and options, and every report loaded in memory. You'll start again from a blank search.</p>
      <div className="stack" style={{ gap: 10, margin: "14px 0" }}>
        <label className="check"><input type="checkbox" checked={forgetKey} onChange={(e) => setForgetKey(e.target.checked)} />
          <span>Also forget the AI key in this browser</span></label>
        <label className="check"><input type="checkbox" checked={server} onChange={(e) => setServer(e.target.checked)} data-testid="clear-server" />
          <span>Also delete my saved data on the server <small>(reports, resumes, saved job links, applications, watches; can't be undone)</small></span></label>
      </div>
      <div className="actions end">
        <button className="btn ghost" onClick={close}>Cancel</button>
        <button className={`btn ${server ? "danger" : "primary"}`} onClick={clear} disabled={busy} data-testid="confirm-clear"><Eraser aria-hidden="true" />{busy ? "Clearing…" : server ? "Clear and delete" : "Clear session"}</button>
      </div>
    </Modal>
  );
}

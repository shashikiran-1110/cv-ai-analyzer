import { useState } from "react";
import { api } from "../api";
import { useAi } from "../ai";
import { useToast } from "../components/Toast";

export function SettingsPage() {
  const ai = useAi();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  async function exportData() {
    const data = await api<unknown>("/api/me/export");
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
    const a = document.createElement("a"); a.href = url; a.download = "cv-match-my-data.json"; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function deleteData() {
    if (!confirm("Delete your resumes, searches and analyses from this server? This can't be undone.")) return;
    setBusy(true);
    try {
      const r = await api<{ deleted: Record<string, number> }>("/api/me", { method: "DELETE" });
      sessionStorage.clear();
      toast(`Deleted ${Object.entries(r.deleted).map(([k, v]) => `${v} ${k}`).join(", ")}.`, "ok");
    } catch (e) { toast((e as Error).message, "error"); } finally { setBusy(false); }
  }
  return (
    <section className="enter" aria-labelledby="h-settings">
      <h1 id="h-settings">Settings & privacy</h1>
      <div className="cols">
        <div className="card">
          <h2>AI provider</h2>
          <p className="muted">{ai.settings.key ? `${ai.settings.provider === "openai" ? "OpenAI" : "Anthropic"} · ${ai.settings.model}` : ai.serverAi ? `Server ${ai.serverAi} key` : "No key added."}
            {" "}Keys stay in this browser and are sent only with AI requests.</p>
          <button className="btn" onClick={() => ai.openModal(true)}>Open AI settings</button>
        </div>
        <div className="card">
          <h2>Your data</h2>
          <p className="muted">Resumes, searches and analyses are kept on this server for a limited time (default 7 days) so a refresh or a shared link keeps working, then deleted automatically.</p>
          <div className="actions">
            <button className="btn" onClick={exportData}>Export my data (JSON)</button>
            <button className="btn danger" onClick={deleteData} disabled={busy}>{busy ? "Deleting…" : "Delete my data"}</button>
          </div>
        </div>
      </div>
    </section>
  );
}

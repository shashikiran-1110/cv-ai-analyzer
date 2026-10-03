import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, post } from "../api";
import type { Me } from "../types";
import { useAi } from "../ai";
import { useToast } from "../components/Toast";

export function SettingsPage() {
  const ai = useAi();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/api/me") });
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState<{ delivery: string; dev_link?: string } | null>(null);
  const [extToken, setExtToken] = useState("");
  useEffect(() => {
    if (params.get("signin") === "ok") toast("Signed in. Your work from this browser is now saved to your account.", "ok");
    if (params.get("signin") === "expired") toast("That sign-in link expired or was already used. Request a new one.", "error");
  }, [params]); // eslint-disable-line react-hooks/exhaustive-deps
  async function signIn() {
    try { setSent(await post("/api/auth/request", { email })); } catch (e) { toast((e as Error).message, "error"); }
  }
  async function signOut() {
    await fetch("/api/auth/logout", { method: "POST" });
    void qc.invalidateQueries(); toast("Signed out.", "ok");
  }
  async function newToken() {
    try { setExtToken((await post<{ token: string }>("/api/ext/tokens", {})).token); } catch (e) { toast((e as Error).message, "error"); }
  }
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
        <div className="card" data-testid="account">
          <h2>Account</h2>
          {me.data?.user ? <>
            <p>Signed in as <b>{me.data.user.email}</b>. Your resumes, reports, tracker and watches are kept for {Math.round(me.data.retention_days)} days.</p>
            <button className="btn" onClick={signOut}>Sign out</button>
          </> : <>
            <p className="muted">Optional. Without an account everything works in this browser and is deleted after {Math.round(me.data?.retention_days ?? 7)} days. Signing in keeps your work, syncs it across devices and enables email digests.</p>
            <form className="key-row" onSubmit={(e) => { e.preventDefault(); void signIn(); }}>
              <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" aria-label="Email" />
              <button className="btn primary">Email me a sign-in link</button>
            </form>
            {sent && <p className="small">{sent.delivery === "email" ? "Check your inbox for the link (valid 15 minutes)." : "No mail server is configured, so the link was written to the server log."}
              {sent.dev_link && <> <a href={sent.dev_link} data-testid="dev-link">Open the sign-in link</a> (local/demo mode)</>}</p>}
          </>}
        </div>
        <div className="card">
          <h2>Browser extension</h2>
          <p className="muted">Score any job page you're viewing (LinkedIn, Indeed, Wellfound, company sites) against your latest resume and save it to your tracker. Load the <code>extension/</code> folder as an unpacked extension, then paste a token in its options.</p>
          <div className="actions"><button className="btn" onClick={newToken}>Create extension token</button>
            <button className="btn danger" onClick={async () => { await api("/api/ext/tokens", { method: "DELETE" }); setExtToken(""); toast("All extension tokens revoked.", "ok"); }}>Revoke all</button></div>
          {extToken && <p className="token" data-testid="ext-token"><code>{extToken}</code> <small className="muted">Shown once. Copy it now.</small></p>}
        </div>
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

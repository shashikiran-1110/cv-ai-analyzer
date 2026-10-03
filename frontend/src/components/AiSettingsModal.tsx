import { useState } from "react";
import { DEFAULT_MODELS, useAi, type AiSettings } from "../ai";
import type { Provider } from "../types";
import { Modal } from "./Modal";
import { Alert } from "./ui";

export function AiSettingsModal() {
  const ai = useAi();
  const [draft, setDraft] = useState<AiSettings>(ai.settings);
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; warning?: boolean; message: string } | null>(null);

  const set = (patch: Partial<AiSettings>) => { setDraft({ ...draft, ...patch }); setResult(null); };
  const setProvider = (p: Provider) => set({ provider: p, model: DEFAULT_MODELS[p] });

  async function verifyAndSave() {
    setBusy(true);
    const r = await ai.verify(draft);
    setResult(r);
    if (r.ok) ai.save(draft);
    setBusy(false);
    if (r.ok && !r.warning) setTimeout(() => ai.openModal(false), 700);
  }

  return (
    <Modal title="AI assistant settings" onClose={() => ai.openModal(false)}>
      <p className="muted">
        Add your own API key to unlock AI-written advice, the chat assistant, and per-job cover letters, resume rewrites and interview prep.
        Your key stays in <b>this browser</b> and is sent only with your AI requests; the server never stores or logs it.
      </p>
      <div className="form-grid one">
        <div className="field">
          <span>Provider</span>
          <div className="seg" role="radiogroup" aria-label="Provider">
            {(["openai", "anthropic"] as Provider[]).map((p) => (
              <button key={p} type="button" role="radio" aria-checked={draft.provider === p} onClick={() => setProvider(p)}>
                {p === "openai" ? "OpenAI" : "Anthropic"}
              </button>
            ))}
          </div>
        </div>
        <label className="field">
          <span>API key</span>
          <div className="key-row">
            <input type={show ? "text" : "password"} value={draft.key} autoComplete="off" spellCheck={false}
              placeholder={draft.provider === "openai" ? "sk-…" : "sk-ant-…"}
              onChange={(e) => set({ key: e.target.value })}
              onKeyDown={(e) => { if (e.key === "Enter" && draft.key.trim()) void verifyAndSave(); }} />
            <button type="button" className="btn" onClick={() => setShow(!show)} aria-pressed={show}>{show ? "Hide" : "Show"}</button>
          </div>
        </label>
        <label className="field">
          <span>Model</span>
          <input value={draft.model} onChange={(e) => set({ model: e.target.value })} spellCheck={false} />
          <small>Default for {draft.provider === "openai" ? "OpenAI" : "Anthropic"}: {DEFAULT_MODELS[draft.provider]}. Change it if your account uses a different model.</small>
        </label>
        <label className="check">
          <input type="checkbox" checked={draft.remember} onChange={(e) => set({ remember: e.target.checked })} />
          <span>Remember this key on this device (otherwise it's forgotten when you close the tab)</span>
        </label>
      </div>

      {ai.serverAi && !draft.key.trim() && <Alert kind="info">The server has a {ai.serverAi} key configured, so AI works without entering one here.</Alert>}
      {result && <Alert kind={result.ok ? (result.warning ? "warn" : "ok") : "error"}>{result.message}</Alert>}

      <div className="actions end">
        {ai.settings.key && <button className="btn" onClick={() => { ai.clear(); setDraft({ ...draft, key: "", remember: false }); setResult(null); }}>Remove key</button>}
        <button className="btn primary" disabled={!draft.key.trim() || !draft.model.trim() || busy} onClick={verifyAndSave}>
          {busy ? "Verifying…" : "Verify & save"}
        </button>
      </div>
      <p className="fine">Verification only reads the model's metadata, so it's instant and uses no tokens. Resume text is sent to your provider only when you run AI features.</p>
    </Modal>
  );
}

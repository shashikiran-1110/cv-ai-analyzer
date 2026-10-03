import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { aiHeaders, api, post } from "./api";
import type { AppConfig, Provider, VerifyResult } from "./types";

export interface AiSettings { provider: Provider; model: string; key: string; remember: boolean }
export type AiStatus = "none" | "checking" | "ok" | "warn" | "bad";

interface Ctx {
  settings: AiSettings;
  status: AiStatus;
  message: string;
  serverAi: Provider | null;
  usable: boolean;                       // a key is configured (browser or server) and not known-bad
  headers: Record<string, string>;
  save: (s: AiSettings) => void;
  verify: (s?: AiSettings) => Promise<VerifyResult>;
  clear: () => void;
  modalOpen: boolean;
  openModal: (open: boolean) => void;
  config: AppConfig | null;
}

const AiCtx = createContext<Ctx | null>(null);
export const useAi = () => { const c = useContext(AiCtx); if (!c) throw new Error("AiProvider missing"); return c; };

const K = { meta: "cvm.ai.meta", key: "cvm.ai.key" };
const DEFAULT_MODELS: Record<Provider, string> = { openai: "gpt-5.6-luna", anthropic: "claude-sonnet-5-5" };

function load(): AiSettings {
  let meta: Partial<AiSettings> = {};
  let key = "", remember = false;
  try {
    meta = JSON.parse(localStorage.getItem(K.meta) || "{}");
    const local = localStorage.getItem(K.key);
    key = local || sessionStorage.getItem(K.key) || "";
    remember = !!local;
  } catch { /* storage unavailable (private mode) */ }
  const provider: Provider = meta.provider === "anthropic" ? "anthropic" : "openai";
  return { provider, model: meta.model || DEFAULT_MODELS[provider], key, remember };
}

export function AiProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<AiSettings>(load);
  const [status, setStatus] = useState<AiStatus>("none");
  const [message, setMessage] = useState("");
  const [modalOpen, openModal] = useState(false);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const seq = useRef(0);

  const verify = useCallback(async (s: AiSettings = settings): Promise<VerifyResult> => {
    const id = ++seq.current;
    setStatus("checking"); setMessage("Checking key…");
    let r: VerifyResult;
    try { r = await post<VerifyResult>("/api/ai/verify", {}, aiHeaders(s)); }
    catch (e) { r = { ok: false, message: (e as Error).message }; }
    if (id === seq.current) {
      setStatus(r.ok ? (r.warning ? "warn" : "ok") : "bad"); setMessage(r.message);
    }
    return r;
  }, [settings]);

  const save = useCallback((s: AiSettings) => {
    setSettings(s);
    try {
      localStorage.setItem(K.meta, JSON.stringify({ provider: s.provider, model: s.model }));
      sessionStorage.removeItem(K.key); localStorage.removeItem(K.key);
      if (s.key) (s.remember ? localStorage : sessionStorage).setItem(K.key, s.key);
    } catch { /* ignore */ }
  }, []);

  const clear = useCallback(() => {
    seq.current++;
    save({ ...settings, key: "", remember: false });
    setStatus("none"); setMessage("");
  }, [save, settings]);

  useEffect(() => {
    api<AppConfig>("/api/config").then(setConfig).catch(() => {});
    if (settings.key) void verify(settings);   // silent re-check of a saved key on load
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const serverAi = config?.server_ai ?? null;
  const value = useMemo<Ctx>(() => ({
    settings, status, message, serverAi,
    usable: (!!settings.key.trim() && status !== "bad") || (!settings.key.trim() && !!serverAi),
    headers: aiHeaders(settings), save, verify, clear, modalOpen, openModal, config,
  }), [settings, status, message, serverAi, save, verify, clear, modalOpen, config]);

  return <AiCtx.Provider value={value}>{children}</AiCtx.Provider>;
}

export { DEFAULT_MODELS };

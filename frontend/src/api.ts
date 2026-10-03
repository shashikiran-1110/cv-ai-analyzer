import type { AiSettings } from "./ai";

export class ApiError extends Error {
  constructor(message: string, public status = 0) { super(message); }
}

export const SERVER_DOWN = `Can't reach the app's API server at ${location.origin}. Make sure the backend is running (./run.sh), then retry.`;

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    const d = body?.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((x) => x.msg).join("; ");
  } catch { /* non-JSON body: usually a proxy/dev-server error page */ }
  if (res.status >= 500) return `The API server isn't responding properly (HTTP ${res.status}). If you're using the Vite dev server, start the backend too (uvicorn app.main:app). ${res.statusText || ""}`.trim();
  if (res.status === 404) return `API endpoint not found (HTTP 404): ${new URL(res.url).pathname}. The backend may be an older version; restart ./run.sh.`;
  return `Request failed (HTTP ${res.status} ${res.statusText}).`.trim();
}

export function aiHeaders(s: AiSettings | null | undefined): Record<string, string> {
  if (!s || !s.key.trim()) return {};
  return { "X-AI-Provider": s.provider, "X-AI-Key": s.key.trim(), "X-AI-Model": s.model.trim() };
}

export async function api<T>(url: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try { res = await fetch(url, init); }
  catch { throw new ApiError(SERVER_DOWN); }
  if (!res.ok) throw new ApiError(await errorMessage(res), res.status);
  return res.json() as Promise<T>;
}

export const post = <T,>(url: string, body: unknown, headers: Record<string, string> = {}) =>
  api<T>(url, { method: "POST", headers: { "Content-Type": "application/json", ...headers }, body: JSON.stringify(body) });

/** POST that streams Server-Sent Events; yields text chunks, throws ApiError on an `error` event. */
export async function* streamPost(url: string, body: unknown, headers: Record<string, string>, signal?: AbortSignal): AsyncGenerator<string> {
  let res: Response;
  try {
    res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json", ...headers }, body: JSON.stringify(body), signal });
  } catch (e) {
    if ((e as Error).name === "AbortError") return;
    throw new ApiError(SERVER_DOWN);
  }
  if (!res.ok || !res.body) throw new ApiError(await errorMessage(res), res.status);
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return;
      buf += dec.decode(value, { stream: true });
      let i: number;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const frame = buf.slice(0, i); buf = buf.slice(i + 2);
        let ev = "message", data = "";
        for (const line of frame.split("\n")) {
          if (line.startsWith("event:")) ev = line.slice(6).trim();
          else if (line.startsWith("data:")) data += line.slice(5).trim();
        }
        if (data === "[DONE]") return;
        if (!data) continue;
        const obj = JSON.parse(data);
        if (ev === "error") throw new ApiError(obj.message || "The AI response failed.");
        if (obj.t) yield obj.t as string;
      }
    }
  } catch (e) {
    if ((e as Error).name === "AbortError") return;
    throw e;
  } finally {
    reader.cancel().catch(() => {});
  }
}

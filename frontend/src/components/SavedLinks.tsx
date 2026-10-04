import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ClipboardPaste, ExternalLink, Trash, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, post } from "../api";
import type { SavedLink } from "../types";
import { StatusIcon } from "./Icons";
import { useToast } from "./Toast";
import { safeUrl } from "./ui";

const URL_RE = /https?:\/\/[^\s<>"'`]+/gi;
/** Every http(s) link in any pasted text (trailing punctuation trimmed). */
export const extractUrls = (text: string) =>
  [...new Set((text.match(URL_RE) ?? []).map((u) => u.replace(/[.,;:!?)\]}>»”’]+$/, "")))];

export function useSavedLinks() {
  return useQuery({ queryKey: ["links"], queryFn: () => api<SavedLink[]>("/api/links"), staleTime: 10_000 });
}

/** Saved job links: kept on the server for this browser/account until discarded; every search fetches them. */
export function SavedLinks({ text, onText, onHasLinks }: { text: string; onText: (t: string) => void; onHasLinks: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const links = useSavedLinks();
  const [busy, setBusy] = useState(false);
  const timer = useRef<number>(0);

  async function save(raw: string, from: "typed" | "clipboard") {
    const urls = extractUrls(raw);
    if (!urls.length) { if (from === "clipboard") toast("No links found on the clipboard.", "info"); return false; }
    setBusy(true);
    try {
      const r = await post<{ links: SavedLink[]; added: number; duplicates: number; rejected: { url: string; reason: string }[]; full: boolean }>("/api/links", { text: raw });
      qc.setQueryData(["links"], r.links);
      onHasLinks();
      const bits = [r.added ? `Saved ${r.added} link${r.added > 1 ? "s" : ""}` : "", r.duplicates ? `${r.duplicates} already saved` : "",
        r.rejected.length ? `${r.rejected.length} rejected (${r.rejected[0].reason})` : "", r.full ? "list is full (200)" : ""].filter(Boolean);
      if (bits.length) toast(bits.join(" · ") + ".", r.rejected.length ? "info" : "ok");
      return true;
    } catch (e) { toast((e as Error).message, "error"); return false; }
    finally { setBusy(false); }
  }

  // typed/pasted text: save the links shortly after the user stops typing, then clear the box
  useEffect(() => {
    window.clearTimeout(timer.current);
    if (!extractUrls(text).length) return;
    timer.current = window.setTimeout(async () => { if (await save(text, "typed")) onText(""); }, 900);
    return () => window.clearTimeout(timer.current);
  }, [text]);  // eslint-disable-line react-hooks/exhaustive-deps

  async function fromClipboard() {
    try {
      const t = await navigator.clipboard.readText();
      await save(t, "clipboard");
    } catch {
      toast("The browser blocked clipboard access. Paste into the box below instead (Ctrl/⌘ V).", "info");
    }
  }
  async function discard(path: string, msg: string) {
    try { await api(path, { method: "DELETE" }); void qc.invalidateQueries({ queryKey: ["links"] }); toast(msg, "ok"); }
    catch (e) { toast((e as Error).message, "error"); }
  }

  const list = links.data ?? [];
  const fetched = list.filter((l) => l.status === "ok").length;
  return (
    <div className="saved-links">
      <div className="actions">
        <button type="button" className="btn small" onClick={fromClipboard} disabled={busy}><ClipboardPaste aria-hidden="true" />Paste from clipboard</button>
        {fetched > 0 && <button type="button" className="btn small ghost" onClick={() => discard("/api/links?only=ok", `Discarded ${fetched} fetched link${fetched > 1 ? "s" : ""}.`)}>Discard fetched</button>}
        {list.length > 0 && <button type="button" className="btn small ghost danger" onClick={() => discard("/api/links", "Discarded all saved links.")}><Trash aria-hidden="true" />Discard all</button>}
        <small className="muted" style={{ marginLeft: "auto" }}>{list.length} saved · kept until you discard them</small>
      </div>
      <textarea rows={2} value={text} aria-label="Job URLs" onChange={(e) => onText(e.target.value)}
        placeholder={"Paste job links or any text containing them; they're saved automatically.\nhttps://jobs.lever.co/acme/… · https://www.linkedin.com/jobs/view/…"} />
      {list.length > 0 && (
        <ul className="link-list">
          {list.map((l) => (
            <li key={l.id} className={`link-${l.status}`}>
              {l.status === "new" ? <span className="si" style={{ background: "var(--surface-2)" }} aria-label="not fetched yet" /> : <StatusIcon s={l.status === "ok" ? "ok" : "bad"} />}
              <div className="link-main">
                <a href={safeUrl(l.url)} target="_blank" rel="noopener noreferrer" title={l.url}>
                  {l.title ? `${l.title}${l.company ? ` · ${l.company}` : ""}` : l.url.replace(/^https?:\/\/(www\.)?/, "")}<ExternalLink size={11} aria-hidden="true" /></a>
                <small className={l.status === "failed" ? "warn-text" : "muted"}>{l.status === "new" ? "Will be fetched on the next search" : l.status === "ok" ? "Fetched" : l.message || "Couldn't be fetched"}</small>
              </div>
              <button type="button" className="icon-btn" aria-label={`Discard ${l.url}`} title="Discard" onClick={() => discard(`/api/links/${l.id}`, "Link discarded.")}><X /></button>
            </li>
          ))}
        </ul>
      )}
      <small className="muted">Wellfound and Indeed often block automated access; when a link fails, open it and use “Paste jobs”.</small>
    </div>
  );
}

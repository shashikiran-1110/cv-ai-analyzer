import { useCallback, useEffect, useRef, useState } from "react";
import { streamPost } from "../api";

/** Streams an SSE endpoint into `text`. Starting a new run aborts the previous one. */
export function useStream() {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const ctl = useRef<AbortController | null>(null);

  const stop = useCallback(() => ctl.current?.abort(), []);
  useEffect(() => () => ctl.current?.abort(), []);

  const run = useCallback(async (url: string, body: unknown, headers: Record<string, string>) => {
    ctl.current?.abort();
    const c = new AbortController();
    ctl.current = c;
    setText(""); setErr(""); setBusy(true);
    let acc = "";
    try {
      for await (const t of streamPost(url, body, headers, c.signal)) { acc += t; setText(acc); }
    } catch (e) { setErr((e as Error).message); }
    finally { if (ctl.current === c) setBusy(false); }
    return acc;
  }, []);

  const reset = useCallback(() => { ctl.current?.abort(); setText(""); setErr(""); setBusy(false); }, []);
  return { text, busy, err, run, stop, reset };
}

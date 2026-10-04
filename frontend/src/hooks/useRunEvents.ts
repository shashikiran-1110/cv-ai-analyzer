import { useEffect, useRef } from "react";

export type RunEvent = { type: string; data: any; seq: number };

/** Subscribe to GET /api/runs/{id}/events (SSE). The browser reconnects automatically with Last-Event-ID. */
export function useRunEvents(runId: string | null | undefined, onEvent: (e: RunEvent) => void, onGone?: () => void) {
  const handler = useRef(onEvent);
  handler.current = onEvent;
  const gone = useRef(onGone);
  gone.current = onGone;
  useEffect(() => {
    if (!runId || typeof EventSource === "undefined") return;
    const es = new EventSource(`/api/runs/${runId}/events`);
    let finished = false;
    const types = ["source.progress", "jobs.ready", "insight.started", "insight.ready", "strategy.ready", "deep.progress", "deep.done", "deep.skipped", "agent.step",
      "agent.question", "agent.edit", "agent.done", "run.finished"];
    const listeners = types.map((t) => {
      const fn = (ev: MessageEvent) => {
        let data: any = {};
        try { data = JSON.parse(ev.data); } catch { /* ignore */ }
        if (t === "run.finished") { finished = true; es.close(); }
        handler.current({ type: t, data, seq: Number(ev.lastEventId) || 0 });
      };
      es.addEventListener(t, fn as EventListener);
      return [t, fn] as const;
    });
    es.onerror = () => {
      // 404 (unknown run, e.g. after a server restart) closes the stream; let the caller refetch.
      if (!finished && es.readyState === EventSource.CLOSED) gone.current?.();
    };
    return () => { listeners.forEach(([t, fn]) => es.removeEventListener(t, fn as EventListener)); es.close(); };
  }, [runId]);
}

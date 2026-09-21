"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { consumeRunEvents, type RunEvent } from "@/lib/api/run-events";

export function useRunEvents(requestId: string | null) {
  const active = useRef<AbortController | null>(null);
  const [state, setState] = useState<{ event?: RunEvent; connection: string; error?: Error }>({
    connection: "idle",
  });
  useEffect(() => {
    if (!requestId) return;
    const controller = new AbortController();
    active.current = controller;
    void consumeRunEvents(requestId, {
      signal: controller.signal,
      onEvent: (event) => setState((previous) => ({ ...previous, event })),
      onConnection: (connection) =>
        setState((previous) =>
          connection === "connecting" ? { connection } : { ...previous, connection },
        ),
    }).catch((error: Error) => {
      if (!controller.signal.aborted)
        setState((previous) => ({ ...previous, error, connection: "error" }));
    });
    return () => controller.abort();
  }, [requestId]);
  const cancel = useCallback(() => {
    active.current?.abort();
    setState((previous) => ({ ...previous, connection: "cancelled" }));
  }, []);
  return requestId ? { ...state, cancel } : { connection: "idle", cancel };
}

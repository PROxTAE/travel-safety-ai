import { z } from "zod";
import { ApiError, mapApiError } from "./client";
import { createRequestId } from "./id";
import type { components } from "./generated/public-api";
type Schemas = components["schemas"];
type EventPayloads = {
  "run.accepted": Schemas["RunAccepted"];
  "run.progress": Schemas["RunProgress"];
  "run.needs_input": Schemas["RunNeedsInput"];
  "run.degraded": Schemas["RunDegraded"];
  "run.completed": Schemas["RunCompleted"];
  "run.failed": Schemas["RunFailed"];
  heartbeat: Schemas["Heartbeat"];
};

const request = { request_id: z.uuid() };
const status = z.enum([
  "QUEUED",
  "RUNNING",
  "NEEDS_INPUT",
  "COMPLETED",
  "PARTIAL",
  "FAILED",
  "CANCELLED",
]);
const events = {
  "run.accepted": z.object({ ...request, status, submitted_at: z.string() }),
  "run.progress": z.object({
    ...request,
    stage: z.enum([
      "VALIDATING",
      "FETCHING_EXTERNAL_DATA",
      "INTEGRATING_DATA",
      "ASSESSING_RISK",
      "RETRIEVING_GUIDANCE",
      "EVALUATING_ROUTES",
      "MAKING_DECISION",
      "EXPLAINING",
      "FORMATTING_RESPONSE",
    ]),
    percent: z.number().min(0).max(100).nullable().optional(),
    message_key: z.string(),
  }),
  "run.needs_input": z.object({
    ...request,
    missing_fields: z.array(z.string()),
    prompt_key: z.string(),
  }),
  "run.degraded": z.object({
    ...request,
    service: z.string(),
    reason: z.enum([
      "TIMEOUT",
      "UNAVAILABLE",
      "RATE_LIMITED",
      "STALE_DATA",
      "PARTIAL_COVERAGE",
      "NOT_CONFIGURED",
      "SCHEMA_MISMATCH",
    ]),
    retrying: z.boolean(),
  }),
  "run.completed": z.object({
    ...request,
    recommendation_id: z.uuid(),
    result_url: z.string(),
    status,
  }),
  "run.failed": z.object({
    ...request,
    error: z.object({
      code: z.enum([
        "VALIDATION_ERROR",
        "AUTHENTICATION_REQUIRED",
        "FORBIDDEN",
        "NOT_FOUND",
        "CONFLICT",
        "IDEMPOTENCY_CONFLICT",
        "RATE_LIMITED",
        "DEPENDENCY_TIMEOUT",
        "DEPENDENCY_UNAVAILABLE",
        "INSUFFICIENT_EVIDENCE",
        "UNSUPPORTED_COVERAGE",
        "POLICY_VALIDATION_FAILED",
        "INTERNAL_ERROR",
      ]),
      message: z.string(),
      retryable: z.boolean(),
    }),
  }),
  heartbeat: z.object({ server_time: z.string() }),
} satisfies { [K in keyof EventPayloads]: z.ZodType<EventPayloads[K]> };
export type RunEvent = {
  [K in keyof typeof events]: { id: string; event: K; data: z.infer<(typeof events)[K]> };
}[keyof typeof events];

export function createSseParser(
  emit: (event: RunEvent) => void,
  retry: (ms: number) => void = () => {},
) {
  let buffer = "",
    event = "",
    id = "",
    data: string[] = [];
  return (chunk: string) => {
    buffer += chunk;
    if (buffer.length > 1_000_000) throw new Error("SSE frame too large");
    let match: RegExpExecArray | null;
    while ((match = /\r\n|\r(?!$)|\n/.exec(buffer))) {
      const line = buffer.slice(0, match.index);
      buffer = buffer.slice(match.index + match[0].length);
      if (!line) {
        if (data.length && Object.hasOwn(events, event)) {
          const name = event as keyof typeof events;
          const parsed = events[name].safeParse(JSON.parse(data.join("\n")));
          if (!parsed.success || (name !== "heartbeat" && !id))
            throw new Error("Invalid run event");
          emit({ event: name, id, data: parsed.data } as RunEvent);
        }
        event = "";
        data = [];
        id = "";
      } else if (!line.startsWith(":")) {
        const colon = line.indexOf(":");
        const field = colon < 0 ? line : line.slice(0, colon);
        const value = colon < 0 ? "" : line.slice(colon + 1).replace(/^ /, "");
        if (field === "event") event = value;
        if (field === "data") {
          data.push(value);
          if (data.reduce((size, part) => size + part.length, 0) > 1_000_000)
            throw new Error("SSE frame too large");
        }
        if (field === "id" && !value.includes("\0")) id = value;
        if (field === "retry" && /^\d+$/.test(value))
          retry(Math.min(30_000, Math.max(250, Number(value))));
      }
    }
  };
}

function delay(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    signal.throwIfAborted();
    const abort = () => {
      clearTimeout(timer);
      reject(signal.reason);
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", abort);
      resolve();
    }, ms);
    signal.addEventListener("abort", abort, { once: true });
  });
}

export async function consumeRunEvents(
  requestId: string,
  options: {
    signal: AbortSignal;
    onEvent: (event: RunEvent) => void;
    onConnection?: (state: "connecting" | "connected" | "reconnecting" | "completed") => void;
    fetcher?: typeof fetch;
    heartbeatMs?: number;
    maxReconnects?: number;
  },
) {
  let lastId = "",
    retryMs = 1000,
    terminal = false;
  const seen = new Set<string>();
  const fetcher = options.fetcher ?? fetch;
  for (let attempt = 0; !options.signal.aborted; attempt++) {
    let retryAfterMs = 0;
    options.onConnection?.(attempt ? "reconnecting" : "connecting");
    const connection = new AbortController();
    const signal = AbortSignal.any([options.signal, connection.signal]);
    let timer: ReturnType<typeof setTimeout> | undefined;
    const heartbeat = () => {
      clearTimeout(timer);
      timer = setTimeout(() => connection.abort(), options.heartbeatMs ?? 45_000);
    };
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    try {
      heartbeat();
      const response = await fetcher(
        `/api/backend/api/v1/runs/${encodeURIComponent(requestId)}/events`,
        {
          headers: {
            Accept: "text/event-stream",
            "X-Correlation-ID": createRequestId(),
            ...(lastId ? { "Last-Event-ID": lastId } : {}),
          },
          credentials: "same-origin",
          signal,
        },
      );
      if (!response.ok) throw await mapApiError(response);
      if (!response.headers.get("Content-Type")?.includes("text/event-stream") || !response.body)
        throw new ApiError("INVALID_STREAM", 422);
      options.onConnection?.("connected");
      const parse = createSseParser(
        (event) => {
          if (event.event === "heartbeat") return;
          if (event.data.request_id !== requestId) throw new ApiError("INVALID_STREAM", 422);
          if (seen.has(event.id)) return;
          seen.add(event.id);
          lastId = event.id;
          if (seen.size > 2000) seen.delete(seen.values().next().value!);
          options.onEvent(event);
          terminal = ["run.completed", "run.failed", "run.needs_input"].includes(event.event);
        },
        (ms) => {
          retryMs = ms;
        },
      );
      reader = response.body.getReader();
      const decoder = new TextDecoder();
      while (!terminal) {
        const { value, done } = await reader.read();
        if (done) break;
        heartbeat();
        parse(decoder.decode(value, { stream: true }));
      }
      if (terminal) {
        options.onConnection?.("completed");
        return;
      }
    } catch (error) {
      if (options.signal.aborted) return;
      if (error instanceof ApiError && error.status >= 400 && error.status < 500) throw error;
      if (error instanceof ApiError) retryAfterMs = error.retryAfterMs;
      if (attempt >= (options.maxReconnects ?? 5)) throw error;
    } finally {
      clearTimeout(timer);
      await reader?.cancel().catch(() => {});
      connection.abort();
    }
    if (attempt >= (options.maxReconnects ?? 5)) throw new ApiError("STREAM_DISCONNECTED", 503);
    try {
      await delay(Math.max(retryAfterMs, Math.min(retryMs * 2 ** attempt, 30_000)), options.signal);
    } catch {
      return;
    }
  }
}

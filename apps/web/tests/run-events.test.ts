// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { consumeRunEvents, createSseParser } from "@/lib/api/run-events";
const id = "00000000-0000-4000-8000-000000000001";
const frame = (event: string, eventId: string, data: object) =>
  `id: ${eventId}\nevent: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
const progress = frame("run.progress", "1", {
  request_id: id,
  stage: "VALIDATING",
  percent: null,
  message_key: "run.validating",
});
const complete = frame("run.completed", "2", {
  request_id: id,
  recommendation_id: id,
  result_url: `/api/v1/recommendations/${id}`,
  status: "COMPLETED",
});
const stream = (body: string) =>
  new Response(body, { headers: { "Content-Type": "text/event-stream" } });
afterEach(() => vi.useRealTimers());
describe("run events", () => {
  it("parses split CRLF frames, ignores comments, strips noncontract content", () => {
    const emit = vi.fn();
    const parse = createSseParser(emit);
    const value = ": heartbeat\r\n" + progress.replace(/\n/g, "\r\n");
    for (const char of value) parse(char);
    expect(emit).toHaveBeenCalledTimes(1);
    expect(emit.mock.calls[0][0]).toMatchObject({
      id: "1",
      event: "run.progress",
      data: { percent: null },
    });
  });
  it("rejects malformed contract payloads", () => {
    expect(() =>
      createSseParser(() => {})(frame("run.progress", "1", { stage: "SECRET_REASONING" })),
    ).toThrow("Invalid run event");
  });
  it("reconnects with Last-Event-ID, deduplicates replay and stops at completion", async () => {
    vi.useFakeTimers();
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(stream(progress))
      .mockResolvedValueOnce(stream(progress + complete));
    const emit = vi.fn();
    const run = consumeRunEvents(id, {
      signal: new AbortController().signal,
      onEvent: emit,
      fetcher,
    });
    await vi.advanceTimersByTimeAsync(1000);
    await run;
    expect(fetcher.mock.calls[1][1].headers["Last-Event-ID"]).toBe("1");
    expect(emit.mock.calls.map(([event]) => event.event)).toEqual([
      "run.progress",
      "run.completed",
    ]);
  });
  it("does not reconnect after cancellation during backoff", async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    const fetcher = vi.fn().mockResolvedValue(stream(""));
    const run = consumeRunEvents(id, { signal: controller.signal, onEvent: vi.fn(), fetcher });
    await vi.advanceTimersByTimeAsync(1);
    controller.abort();
    await run;
    await vi.advanceTimersByTimeAsync(30000);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("does not retry authentication errors", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(null, { status: 401 }));
    await expect(
      consumeRunEvents(id, { signal: new AbortController().signal, onEvent: vi.fn(), fetcher }),
    ).rejects.toMatchObject({ status: 401 });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("reconnects when the heartbeat watchdog expires", async () => {
    vi.useFakeTimers();
    const fetcher = vi
      .fn()
      .mockImplementationOnce(
        (_url, init) =>
          new Promise((_resolve, reject) =>
            init.signal.addEventListener("abort", () =>
              reject(new DOMException("timeout", "AbortError")),
            ),
          ),
      )
      .mockResolvedValueOnce(stream(complete));
    const run = consumeRunEvents(id, {
      signal: new AbortController().signal,
      onEvent: vi.fn(),
      fetcher,
      heartbeatMs: 100,
    });
    await vi.advanceTimersByTimeAsync(1100);
    await run;
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});

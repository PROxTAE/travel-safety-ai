import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useRunEvents } from "@/features/assessment/use-run-events";
import { consumeRunEvents } from "@/lib/api/run-events";
vi.mock("@/lib/api/run-events", () => ({ consumeRunEvents: vi.fn(() => new Promise(() => {})) }));
describe("useRunEvents lifecycle", () => {
  it("cancels an old run, explicit cancellation, and unmount", () => {
    const { result, rerender, unmount } = renderHook(({ id }) => useRunEvents(id), {
      initialProps: { id: "first" },
    });
    const first = vi.mocked(consumeRunEvents).mock.calls.at(-1)![1].signal;
    rerender({ id: "second" });
    expect(first.aborted).toBe(true);
    const second = vi.mocked(consumeRunEvents).mock.calls.at(-1)![1].signal;
    act(() => result.current.cancel());
    expect(second.aborted).toBe(true);
    expect(result.current.connection).toBe("cancelled");
    rerender({ id: "third" });
    const third = vi.mocked(consumeRunEvents).mock.calls.at(-1)![1].signal;
    unmount();
    expect(third.aborted).toBe(true);
  });
});

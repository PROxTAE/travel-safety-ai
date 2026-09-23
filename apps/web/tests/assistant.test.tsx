import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AssistantView } from "@/features/conversations/assistant-view";
import { api } from "@/lib/api/client";

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
  }),
}));

describe("AssistantView", () => {
  const mockConversations = [
    {
      conversation_id: "conv-1",
      title: "Bangkok Route Safety Assessment",
      trip_id: "trip-1",
      message_count: 3,
      last_message_preview: "Heavy rain advisory on northern highway.",
      created_at: "2026-09-22T00:00:00Z",
      updated_at: "2026-09-22T00:00:00Z",
    },
  ];

  const mockMessages = [
    {
      message_id: "msg-1",
      conversation_id: "conv-1",
      role: "USER",
      content: "Is Highway 1 safe right now?",
      created_at: "2026-09-22T00:01:00Z",
    },
    {
      message_id: "msg-2",
      conversation_id: "conv-1",
      role: "ASSISTANT",
      content: "Highway 1 has moderate rain forecast between 14:00 and 17:00. Recommend alternative route.",
      created_at: "2026-09-22T00:01:05Z",
    },
  ];

  it("renders conversation history and chat messages", async () => {
    vi.spyOn(api, "GET").mockImplementation(async (path) => {
      if (path === "/api/v1/conversations") {
        return { data: { data: mockConversations } } as never;
      }
      if (path === "/api/v1/conversations/{id}/messages") {
        return { data: { data: mockMessages } } as never;
      }
      return { data: null } as never;
    });

    render(<AssistantView conversationId="conv-1" />);

    await waitFor(() => {
      expect(screen.getByText("Bangkok Route Safety Assessment")).toBeInTheDocument();
    });

    expect(screen.queryByText(/Hello! I am your AI Travel Safety Assistant/)).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Type your travel safety question/)).toBeInTheDocument();
  });
});

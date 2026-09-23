import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { POST } from "@/app/api/assistant/chat/route";
import { NextRequest } from "next/server";

describe("Gemini Assistant Chat API Route", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    process.env.GEMINI_API_KEY = "test-gemini-key";
    process.env.GEMINI_MODEL = "gemini-3.6-flash";
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("returns 400 when messages array is empty", async () => {
    const req = new NextRequest("http://localhost:3000/api/assistant/chat", {
      method: "POST",
      body: JSON.stringify({ messages: [] }),
    });

    const res = await POST(req);
    const data = await res.json();

    expect(res.status).toBe(400);
    expect(data.error).toBe("Messages array cannot be empty.");
  });

  it("successfully responds to general conversation using Gemini API", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        candidates: [
          {
            content: {
              parts: [{ text: "สวัสดีครับ! ยินดีที่ได้พูดคุยครับ มีคำถามการเดินทางอะไรให้ผมช่วยไหมครับ" }],
            },
          },
        ],
      }),
    } as unknown as Response);

    const req = new NextRequest("http://localhost:3000/api/assistant/chat", {
      method: "POST",
      body: JSON.stringify({
        messages: [{ role: "user", content: "สวัสดีครับ" }],
      }),
    });

    const res = await POST(req);
    const data = await res.json();

    expect(res.status).toBe(200);
    expect(data.reply).toContain("สวัสดีครับ!");
    expect(data.model).toBeDefined();
    expect(global.fetch).toHaveBeenCalled();
  });

  it("incorporates trip context and live location into the system prompt", async () => {
    let capturedBody: any = null;

    global.fetch = vi.fn().mockImplementation((_url, options) => {
      capturedBody = JSON.parse(options.body);
      return Promise.resolve({
        ok: true,
        json: async () => ({
          candidates: [
            {
              content: {
                parts: [{ text: "เส้นทาง กรุงเทพ ไป เชียงใหม่ ปลอดภัยดีครับ มีฝนเล็กน้อยช่วงบ่าย" }],
              },
            },
          ],
        }),
      } as unknown as Response);
    });

    const req = new NextRequest("http://localhost:3000/api/assistant/chat", {
      method: "POST",
      body: JSON.stringify({
        messages: [{ role: "user", content: "เส้นทางของฉันปลอดภัยไหม" }],
        tripContext: {
          origin: { display_name: "Bangkok, Thailand" },
          destination: { display_name: "Chiang Mai, Thailand" },
          travel_mode: "TRAIN",
          short_summary: "เส้นทางปกติ",
        },
        liveLocation: {
          lat: 13.7563,
          lng: 100.5018,
          address: "Bangkok",
        },
      }),
    });

    const res = await POST(req);
    const data = await res.json();

    expect(res.status).toBe(200);
    expect(data.reply).toContain("กรุงเทพ ไป เชียงใหม่");
    expect(capturedBody).toBeDefined();
    expect(capturedBody.systemInstruction.parts[0].text).toContain("Bangkok, Thailand");
    expect(capturedBody.systemInstruction.parts[0].text).toContain("Chiang Mai, Thailand");
    expect(capturedBody.systemInstruction.parts[0].text).toContain("13.75630");
  });
});

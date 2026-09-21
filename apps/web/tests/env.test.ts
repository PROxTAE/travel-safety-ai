import { describe, expect, it } from "vitest";
import { getPublicEnvironment } from "@/lib/env";

describe("getPublicEnvironment", () => {
  it("accepts a public API URL and optional map configuration", () => {
    expect(
      getPublicEnvironment({ NEXT_PUBLIC_API_BASE_URL: "https://api.example.test" }),
    ).toMatchObject({
      NEXT_PUBLIC_API_BASE_URL: "https://api.example.test",
    });
  });

  it("rejects a missing public API URL", () => {
    expect(() => getPublicEnvironment({})).toThrow();
  });

  it("rejects invalid public map URLs", () => {
    expect(() =>
      getPublicEnvironment({
        NEXT_PUBLIC_API_BASE_URL: "https://api.example.test",
        NEXT_PUBLIC_MAP_TILE_URL: "tiles",
      }),
    ).toThrow();
  });
});

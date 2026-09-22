import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.{ts,tsx}"],
    setupFiles: ["./tests/setup.ts"],
    // A cold Next.js module transform can exceed Vitest's 5s default in the
    // Alpine Docker image even though the synchronous assertion is fast.
    testTimeout: 15_000,
  },
});

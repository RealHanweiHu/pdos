import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    // The repo lives on an iCloud-synced volume; module imports can stall for
    // seconds under sync load, so interaction tests need more headroom than
    // the 5s default to avoid environment-only flakes.
    testTimeout: 20_000,
  },
});

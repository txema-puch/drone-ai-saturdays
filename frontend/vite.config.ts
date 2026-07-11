/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The serve layer (backend/serve/app.py) runs on :8077 in dev. In the Docker
// image nginx proxies /api → the backend, so the frontend always talks to a
// relative /api — only the dev proxy target differs.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5180,
    strictPort: true,
    proxy: {
      "/api": "http://127.0.0.1:8077",
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});

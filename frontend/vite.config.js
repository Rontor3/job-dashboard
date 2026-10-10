import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // ./jobdash dev: Vite on :8000 (the one address the user sees), the api on :8001, the agent service on :8002.
  server: {
    port: 8000, strictPort: true,
    proxy: { "/api": process.env.API_URL || "http://127.0.0.1:8001", "/agent": process.env.AGENT_URL || "http://127.0.0.1:8002" },
  },
  test: { environment: "jsdom", setupFiles: ["./vitest.setup.js"], globals: true },
});

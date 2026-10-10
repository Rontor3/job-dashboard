import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // ./jobdash dev: Vite on :8000 (the one address the user sees), the api behind it on :8001.
  server: { port: 8000, strictPort: true, proxy: { "/api": process.env.API_URL || "http://127.0.0.1:8001" } },
  test: { environment: "jsdom", setupFiles: ["./vitest.setup.js"], globals: true },
});

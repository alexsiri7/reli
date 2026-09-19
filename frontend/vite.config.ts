import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  // Everything emitted must land under assets/: backend/api.py mounts StaticFiles there and answers
  // any other file-like path 404, so a root-level file would not be served at all. The one exception
  // is public/sw.js, which the backend serves by name (#1513).
  build: { assetsDir: "assets" },
  server: { proxy: { "/api": "http://localhost:8000" } },
  // Bound explicitly: Playwright's webServer polls 127.0.0.1, and vite's default `localhost`
  // resolves to ::1 inside the pinned container, where nothing answers over v4.
  preview: { host: "127.0.0.1", port: 4173, strictPort: true },
});

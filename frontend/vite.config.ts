import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  // Everything emitted must land under assets/: backend/api.py mounts StaticFiles there and hands
  // every other path index.html, so a root-level file would be served the bundle instead of itself.
  build: { assetsDir: "assets" },
  server: { proxy: { "/api": "http://localhost:8000" } },
  // Bound explicitly: Playwright's webServer polls 127.0.0.1, and vite's default `localhost`
  // resolves to ::1 inside the pinned container, where nothing answers over v4.
  preview: { host: "127.0.0.1", port: 4173, strictPort: true },
});

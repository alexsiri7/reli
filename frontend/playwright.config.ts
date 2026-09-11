import { defineConfig, devices } from "@playwright/test";

/**
 * Snapshots are only valid from the pinned container whose tag matches the @playwright/test version
 * in package.json — see the Screenshot Tests section of CLAUDE.md. Running these on a developer's
 * host renders with the host's fonts and fails on pixels that mean nothing.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  reporter: "line",
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  use: { baseURL: "http://127.0.0.1:4173" },
  webServer: {
    command: "npm run build && npm run preview",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
  },
});

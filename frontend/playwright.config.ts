import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? 'github' : 'html',
  use: {
    // Default: local preview server. Override with BASE_URL for live-site runs.
    baseURL: process.env.BASE_URL || 'http://localhost:4173',
    screenshot: 'only-on-failure',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
      testMatch: /visual\.spec\.ts/,
    },
    {
      name: 'mobile-chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 390, height: 844 } },
      testMatch: /mobile\.spec\.ts/,
    },
    {
      name: 'dark-chromium',
      use: { ...devices['Desktop Chrome'], colorScheme: 'dark' },
      testMatch: /visual\.spec\.ts/,
    },
    {
      name: 'smoke',
      use: { ...devices['Desktop Chrome'] },
      testMatch: /smoke\.spec\.ts/,
    },
  ],
  // Start a local preview server when not using a live BASE_URL
  ...(process.env.BASE_URL
    ? {}
    : {
        webServer: {
          command: 'npm run build && npm run preview',
          url: 'http://localhost:4173',
          reuseExistingServer: !process.env.CI,
          timeout: 120_000,
        },
      }),
})

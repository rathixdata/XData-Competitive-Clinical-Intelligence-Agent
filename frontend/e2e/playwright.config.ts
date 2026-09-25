import { existsSync } from 'node:fs';
import { defineConfig, devices } from '@playwright/test';

/**
 * E2E smoke tests. Prerequisites: the API on :8000 (see README) with the seeded demo tenant.
 * The Vite dev server is started automatically (or reused if already running).
 * Chromium: set PW_CHROMIUM_PATH, or rely on PLAYWRIGHT_BROWSERS_PATH / the preinstalled /opt/pw-browsers/chromium.
 */
const preinstalled = '/opt/pw-browsers/chromium';
const executablePath = process.env.PW_CHROMIUM_PATH ?? (existsSync(preinstalled) ? preinstalled : undefined);
const baseURL = process.env.E2E_BASE_URL ?? 'http://localhost:5173';

export default defineConfig({
  testDir: '.',
  testMatch: /.*\.spec\.ts/,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list']],
  outputDir: '../test-results',
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    viewport: { width: 1400, height: 900 },
    launchOptions: executablePath ? { executablePath } : {},
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1400, height: 900 } } }],
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command: 'npm run dev',
        cwd: '..',
        url: baseURL,
        reuseExistingServer: true,
        timeout: 60_000,
      },
});

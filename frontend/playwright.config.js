// End-to-end tests: a real browser against the real API + PostgreSQL + Redis.
// Run: npm run e2e      (resets the DEVELOPMENT database to the demo seed first)
import { defineConfig, devices } from '@playwright/test'

// E2E_BASE_URL=http://localhost:8080 npm run e2e   -> test an already running stack
// (e.g. Docker Compose or a deployed environment); you seed its data yourself.
const external = process.env.E2E_BASE_URL

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  // One worker: every test uses the same demo accounts in one database (one server-side
  // cart per customer). Parallel projects would race on that shared state.
  workers: 1,
  fullyParallel: false,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  globalSetup: external ? undefined : './e2e/global-setup.js',
  use: {
    baseURL: external || 'http://localhost:5173',
    trace: 'retain-on-failure', // step-by-step replay of failed runs
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'desktop-chrome', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile-chrome', use: { ...devices['Pixel 7'] } },
  ],
  // Starts the servers unless they are already running (e.g. your own dev servers).
  webServer: external ? undefined : [
    {
      command: '../backend/.venv/bin/uvicorn app.main:app --port 8000',
      cwd: '../backend',
      url: 'http://localhost:8000/api/v1/health',
      reuseExistingServer: true,
    },
    { command: 'npm run dev', url: 'http://localhost:5173', reuseExistingServer: true },
  ],
})

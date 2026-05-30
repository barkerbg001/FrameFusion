import { defineConfig, devices } from '@playwright/test'

const apiEnv = {
  E2E_FAST_RENDER: '1',
  JOB_QUEUE_BACKEND: 'inline',
  RATE_LIMIT_ENABLED: 'false',
  CLEANUP_INTERVAL_SECONDS: '86400',
}

const apiCommand =
  process.platform === 'win32'
    ? `cd ../api && set E2E_FAST_RENDER=1&& set JOB_QUEUE_BACKEND=inline&& set RATE_LIMIT_ENABLED=false&& set CLEANUP_INTERVAL_SECONDS=86400&& python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
    : `cd ../api && E2E_FAST_RENDER=1 JOB_QUEUE_BACKEND=inline RATE_LIMIT_ENABLED=false CLEANUP_INTERVAL_SECONDS=86400 python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: [
    {
      command: apiCommand,
      url: 'http://127.0.0.1:8000/health',
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: apiEnv,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 5173',
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
})

import { defineConfig, devices } from '@playwright/test';
import { API, BASE, PORT } from './e2e/env';

/**
 * End-to-end checks for the dashboard, with screenshots.
 *
 * The suite exists to answer one question that unit tests cannot: **is what the
 * operator sees actually coming from the backend?** Before 21 Sep the answer was
 * no, and nothing caught it — every panel fell back to invented rows on a failed
 * request or an empty list, so a dead backend rendered a full, confident
 * dashboard. A screenshot of that failure is indistinguishable from success,
 * which is exactly why the assertions here check for the *absence* of known
 * fabricated values, not just that the page rendered.
 *
 * Screenshots land in `e2e/screenshots/` and are attached to the HTML report.
 * They are artefacts for reviewing a rehearsal, not golden-image comparisons:
 * live data changes every run, so pixel diffing would fail for the right reason
 * at the wrong time.
 *
 * It runs only against the disposable E2E backend: `make e2e-backend` starts it
 * on indra_e2e (port 8100), and `make e2e` runs this suite. e2e/env.ts refuses
 * an unset, non-loopback or :8000 E2E_API_URL, and e2e/global-setup.ts refuses
 * a backend that cannot prove it is the E2E one. There is no default backend.
 *
 * `webServer` builds the dashboard with NEXT_PUBLIC_API_BASE_URL set to that
 * backend, into .next-e2e so the dev build in .next is left alone, and serves
 * it on :3100. It never reuses a running server, whose build could point
 * anywhere. `npx next build` rather than `npm run build`, whose prebuild step
 * would wipe .next.
 */
export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  // Serial: these tests drive one shared backend and one database. Parallel
  // workers would race each other's submitted reports.
  workers: 1,
  fullyParallel: false,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [
    ['list'],
    ['html', { outputFolder: 'e2e/report', open: 'never' }],
  ],
  use: {
    baseURL: BASE,
    // Every test gets a screenshot, passing or failing -- the point is the
    // artefact, not only the diagnosis.
    screenshot: 'on',
    trace: 'retain-on-failure',
    video: 'off',
    viewport: { width: 1600, height: 1000 },
  },
  projects: [
    {
      name: 'desktop-chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1600, height: 1000 } },
    },
  ],
  webServer: {
    command: `npx next build && npx next start -p ${PORT}`,
    url: BASE,
    reuseExistingServer: false,
    timeout: 300_000,
    env: {
      NEXT_PUBLIC_API_BASE_URL: API,
      // The alerts page also reads the separate Alert Engine (PR #38), which the
      // E2E stack does not run. Pointed at the E2E backend, its calls find
      // nothing and the page shows its empty state, and fixtures.ts can keep
      // refusing every other origin.
      NEXT_PUBLIC_ALERT_ENGINE_BASE_URL: API,
      NEXT_PUBLIC_ALERT_ENGINE_WS_URL: `${new URL(API).origin.replace(/^http/, 'ws')}/ws/alerts`,
      NEXT_DIST_DIR: '.next-e2e',
    },
  },
});

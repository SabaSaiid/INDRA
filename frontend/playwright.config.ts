import { defineConfig, devices } from '@playwright/test';

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
 * `webServer` builds nothing — it serves whatever is already built and expects
 * the backend on :8000. Run `npm run build` and start the API first, or use
 * `npm run e2e` which is wired for exactly that.
 */
export default defineConfig({
  testDir: './e2e',
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
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:3000',
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
    command: 'npm run start',
    url: 'http://localhost:3000',
    reuseExistingServer: true,
    timeout: 120_000,
  },
});

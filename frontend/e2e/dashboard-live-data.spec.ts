import type { Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { test, expect } from './fixtures';
import { API } from './env';

/**
 * The dashboard shows live data, or says it cannot — never invented data.
 *
 * These assertions are written as *negatives* on purpose. Checking that the page
 * rendered proves nothing here: before 21 Sep the dashboard rendered beautifully
 * against a backend that was switched off, because every panel fell back to
 * `mock-data.ts`. The screenshot of that failure looked exactly like success.
 *
 * So the suite checks for the absence of the specific fabricated values that
 * file used to supply. If any of them reappear, a fallback has come back.
 */

const SHOTS = path.join(__dirname, 'screenshots');
fs.mkdirSync(SHOTS, { recursive: true });

/**
 * Strings that only ever existed in the deleted mock-data.ts, plus values the
 * real pipeline provably cannot produce.
 *
 * `0.94` / `AUTO_PUBLISHED`: the maximum confidence achievable while the vision
 * and anomaly factors are offline is 0.80, and AUTO_PUBLISHED needs 0.90. Both
 * appearing together is proof of fabricated data, not of a very confident event.
 */
const FABRICATED_MARKERS = [
  'WX-EV-28231827-A',
  'Kankarbagh Sector 4',
  'AUTO_PUBLISHED',
];

async function shoot(page: Page, name: string) {
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true });
}

/**
 * Wait for the first data pass to settle.
 *
 * Deliberately NOT `networkidle`. The dashboard holds a WebSocket open to
 * /ws/events for live NEW_REPORT pushes, so the network is never idle and that
 * wait times out on every page -- which is exactly how the first run of this
 * suite failed, five times, for a reason that had nothing to do with the data.
 *
 * `domcontentloaded` plus a settle window is the right signal: the fetches are
 * fired from effects on mount and resolve well inside it, and the fade-in
 * animations finish, so screenshots are not caught mid-transition.
 */
async function settle(page: Page) {
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(4000);
}

test.describe('dashboard renders live data or an honest empty state', () => {
  test('backend is reachable and reports healthy', async ({ request }) => {
    const res = await request.get(`${API}/healthz`);
    expect(res.ok()).toBeTruthy();

    const body = await res.json();
    // The DB and the streaming bus are the two critical dependencies. If either
    // is down, everything below tests the wrong thing.
    expect(body.checks.database.status).toBe('up');
    expect(body.checks.streaming_bus.status).toBe('up');
  });

  test('dashboard shows no fabricated values', async ({ page }) => {
    await page.goto('/');
    await settle(page);
    await shoot(page, '01-dashboard');

    const body = await page.locator('body').innerText();
    for (const marker of FABRICATED_MARKERS) {
      expect(body, `"${marker}" is a value only mock-data.ts ever produced`).not.toContain(marker);
    }
  });

  test('KPI numbers come from the backend, not the page', async ({ page }) => {
    const summary = await (await page.request.get(`${API}/api/dashboard/summary`)).json();

    await page.goto('/');
    await settle(page);

    // The strip either shows the backend's own totals, or says it could not
    // load them. What it must never do is show a different number.
    const strip = page.locator('.instrument-strip');
    await expect(strip).toBeVisible();

    const text = await strip.innerText();
    const failed = await page.getByTestId('error-state').count();
    if (failed === 0) {
      expect(text).toContain(String(summary.total_reports));
      expect(text).toContain(String(summary.verified_events));
    }
    await shoot(page, '02-kpi-strip');
  });

  test('a submitted report reaches the dashboard', async ({ page }) => {
    // Only ever against the disposable E2E backend (global-setup.ts). The
    // 'E2E probe' prefix keeps a stray row recognisable wherever it ends up.
    const before = await (await page.request.get(`${API}/api/dashboard/summary`)).json();

    // A real submission through the real endpoint: validated, credibility-scored,
    // written to Postgres and published to Kafka.
    const probe = `E2E probe ${Date.now()}`;
    const submit = await page.request.post(`${API}/api/reports/submit`, {
      data: {
        latitude: 25.5941,
        longitude: 85.1376,
        text: `${probe} — water rising near the underpass, knee deep`,
      },
    });
    expect(submit.status()).toBe(202);

    // The pipeline is asynchronous; poll rather than guess a sleep.
    await expect
      .poll(
        async () => {
          const now = await (await page.request.get(`${API}/api/dashboard/summary`)).json();
          return now.total_reports;
        },
        { timeout: 30_000, intervals: [1000] }
      )
      .toBeGreaterThan(before.total_reports);

    // And the stored row is this probe, not merely any new report.
    await expect
      .poll(
        async () => {
          const res = await page.request.get(`${API}/api/reports/recent?hours=1&unfused_only=false`);
          const rows: Array<{ text: string }> = await res.json();
          return rows.some((r) => r.text.startsWith(probe));
        },
        { timeout: 30_000, intervals: [1000] }
      )
      .toBe(true);

    await page.goto('/');
    await settle(page);
    await shoot(page, '03-after-live-report');
  });

  test('agency alerts are real CAP warnings from named agencies', async ({ page }) => {
    const res = await page.request.get(`${API}/api/alerts/agency?limit=50`);
    expect(res.ok()).toBeTruthy();

    const alerts = await res.json();
    // An empty list is legitimate -- no agency may have a live warning in force.
    // What is not legitimate is an invented one.
    for (const alert of alerts) {
      expect(alert.identifier, 'every alert must carry its SACHET identifier').toBeTruthy();
      expect(alert.sender, 'an alert with no issuing agency is not an alert').toBeTruthy();
      if (alert.severity) {
        expect(['ADVISORY', 'MODERATE', 'HIGH', 'CRITICAL']).toContain(alert.severity);
      }
      // CAP allows "Unknown"; it must map to null, never be invented upward.
      if (alert.raw_severity === 'Unknown') {
        expect(alert.severity).toBeNull();
      }
    }
  });

  test('the dashboard degrades honestly when the backend is unreachable', async ({ page }) => {
    // The regression this whole change exists to prevent: with the API failing,
    // the page must say so rather than quietly showing invented events.
    await page.route('**/api/**', (route) => route.abort('connectionrefused'));

    await page.goto('/');
    await settle(page);
    await shoot(page, '04-backend-unreachable');

    const body = await page.locator('body').innerText();
    for (const marker of FABRICATED_MARKERS) {
      expect(body, `backend down must not produce "${marker}"`).not.toContain(marker);
    }

    // And it must visibly admit the failure somewhere on the page.
    const errors = await page.getByTestId('error-state').count();
    expect(errors, 'a failed dashboard must show at least one error state').toBeGreaterThan(0);
  });
});

test.describe('the other routes render against live data', () => {
  for (const [name, route] of [
    ['teams', '/teams'],
    ['profile', '/profile'],
    ['events', '/events'],
    ['live-map', '/live-map'],
  ] as const) {
    test(`${name} renders without fabricated values`, async ({ page }) => {
      const failures: string[] = [];
      page.on('pageerror', (err) => failures.push(err.message));

      await page.goto(route);
      await settle(page);
      await shoot(page, `route-${name}`);

      expect(failures, `${name} threw during render`).toEqual([]);

      const body = await page.locator('body').innerText();
      for (const marker of FABRICATED_MARKERS) {
        expect(body, `${name} shows "${marker}"`).not.toContain(marker);
      }
    });
  }
});

import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

/**
 * 22 Sep: every page, checked for the invented values removed that day.
 *
 * The 21 Sep suite covered the dashboard and four routes against the markers of
 * the deleted mock-data.ts. It could not see the other half of the problem:
 * constants written straight into JSX — official bulletins credited to IMD and
 * CWC, a cyclone forecast track, an uptime figure, a BigQuery lakehouse. None
 * of those came from a fallback, so none of them tripped a fallback check.
 *
 * Negative assertions again, for the same reason: a page that renders proves
 * nothing, but a page that no longer contains "Cyclone Marut" proves the
 * bulletin is gone.
 */

const SHOTS = path.join(__dirname, 'screenshots');
fs.mkdirSync(SHOTS, { recursive: true });

/** Every one of these was hardcoded somewhere in the dashboard until 22 Sep. */
const INVENTED = [
  // alerts page: four fake official bulletins and a fake broadcast
  'Cyclone "Marut"',
  'Port signal 8 hoisted',
  '2,85,000 cusecs',
  'CAP-INDIA BROADCAST ONLINE',
  'NDMA • ',
  // admin console
  '99.98% Uptime',
  'Zero Breaches',
  'CLEARANCE: LEVEL 5',
  'R.K. Verma authenticated via PKI smartcard',
  'pushed to Puri district civil authorities',
  // datasets, analytics, live map, settings
  'BigQuery',
  'INSAT-3DR',
  '184 GB / Day',
  '1.42M',
  'INFERENCE LATENCY',
  'Cyclone DANA',
  'NDRF Units:',
  '4 Active Feeds',
  'Autonomous Mock Engine',
  'Doppler Weather Radar Heatmap',
  '~6.4 MB',
  // dashboard furniture
  'IMD • NDRF Synced',
  'Grid Synced',
  'IoT hydro-sensors',
];

const ROUTES = [
  ['dashboard', '/'],
  ['alerts', '/alerts'],
  ['admin', '/admin'],
  ['datasets', '/datasets'],
  ['analytics', '/analytics'],
  ['live-map', '/live-map'],
  ['reports', '/reports'],
  ['events', '/events'],
  ['teams', '/teams'],
  ['profile', '/profile'],
  ['settings', '/settings'],
] as const;

test.describe('no page shows the values removed on 22 Sep', () => {
  for (const [name, route] of ROUTES) {
    test(`${name} contains none of them`, async ({ page }) => {
      const failures: string[] = [];
      page.on('pageerror', (err) => failures.push(err.message));

      await page.goto(route);
      await page.waitForLoadState('domcontentloaded');
      await page.waitForTimeout(4000);
      await page.screenshot({ path: path.join(SHOTS, `invented-${name}.png`), fullPage: true });

      expect(failures, `${name} threw during render`).toEqual([]);
      const body = await page.locator('body').innerText();
      for (const marker of INVENTED) {
        expect(body, `${name} still shows "${marker}"`).not.toContain(marker);
      }
    });
  }
});

test('the warnings page labels what is official and what is INDRA', async ({ page, request }) => {
  await page.goto('/alerts');
  await page.waitForTimeout(4000);

  const alerts = await (await request.get('http://localhost:8000/api/alerts/agency?limit=100')).json();
  const events = await (await request.get('http://localhost:8000/api/events?time_range=7d')).json();
  const severe = events.filter((e: any) => ['CRITICAL', 'HIGH'].includes(String(e.severity).toUpperCase()));

  // One card per live SACHET alert and one per severe INDRA event: no more.
  await expect(page.locator('[data-kind="official"]')).toHaveCount(alerts.length);
  await expect(page.locator('[data-kind="indra"]')).toHaveCount(severe.length);
  if (alerts.length > 0) {
    await expect(page.locator('[data-kind="official"]').first()).toContainText('OFFICIAL WARNING');
  }
  await expect(page.getByText('INDRA itself does not issue warnings.')).toBeVisible();
});

test('the admin console reports the health the backend reports', async ({ page, request }) => {
  const health = await (await request.get('http://localhost:8000/healthz')).json();
  await page.goto('/admin');
  await page.waitForTimeout(4000);

  const expected: Record<string, string> = {
    healthy: 'ALL CHECKS UP',
    degraded: 'DEGRADED',
    unhealthy: 'UNHEALTHY',
  };
  await expect(page.getByTestId('overall-health')).toContainText(expected[health.status]);
  await expect(page.getByText('PostgreSQL + PostGIS')).toBeVisible();
});

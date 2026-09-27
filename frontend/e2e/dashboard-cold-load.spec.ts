import type { Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { test, expect } from './fixtures';

/**
 * What a cold load shows, before anybody touches anything.
 *
 * Both defects these tests pin (BUG-043, BUG-044) were invisible to the whole
 * suite — 684 backend tests and 10 Playwright tests were green over both — and
 * were found by opening the console in a browser and looking at it. What they
 * have in common is that they only exist *on first paint*: the map drew its
 * pins correctly the moment any control was clicked, so every test that
 * interacted with the page before asserting would have missed it, and did.
 *
 * So these assertions are made on an untouched page. The only actions allowed
 * before the expectations are `goto` and waiting.
 */

const SHOTS = path.join(__dirname, 'screenshots');
fs.mkdirSync(SHOTS, { recursive: true });

/**
 * Same reasoning as the sibling spec: never `networkidle`, because the
 * dashboard holds a WebSocket open and the network is never idle.
 *
 * The window here is longer, though. The map waits on a remote basemap style —
 * sprites, glyphs and the first tiles — and drawing the pins is the last thing
 * that happens. A short settle would make this test flaky in precisely the
 * direction that hides the bug, so it is generous on purpose.
 */
async function settleMap(page: Page) {
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(9000);
}

test.describe('the dashboard is correct before anyone touches it', () => {
  test('the map draws the pins its own badge is counting', async ({ page }) => {
    await page.goto('/');
    await settleMap(page);
    await page.screenshot({ path: path.join(SHOTS, 'cold-01-map.png') });

    // The badge tells us how many pins the component believes it holds.
    // Parsing it rather than hardcoding a number keeps this test honest against
    // live data, which moves between runs.
    const badge = page.locator('text=/\\d+ map pins/').first();
    await expect(badge, 'the map must state a pin count').toBeVisible();

    const claimed = Number((await badge.innerText()).match(/(\d+) map pins/)![1]);
    test.skip(claimed === 0, 'no pins in the database, nothing to draw');

    // BUG-043: this was 0 while the badge said 42. The map is the product;
    // a map that counts what it does not draw is worse than an empty one,
    // because it looks authoritative.
    const drawn = await page.locator('.maplibregl-marker').count();
    expect(
      drawn,
      `the badge claims ${claimed} pins but the map drew ${drawn} markers`
    ).toBeGreaterThan(0);
  });

  test('a flat KPI delta is not drawn as a decline', async ({ page }) => {
    await page.goto('/');
    await settleMap(page);

    const strip = await page.locator('body').innerText();

    // BUG-044: `isPositive = delta > 0` fed a single ternary, so every zero
    // delta rendered a red downward arrow. Two of the readings carry a
    // hardcoded delta of 0 because they have no comparison window at all, so
    // the arrow was drawing a trend that does not exist.
    expect(
      strip,
      'a change of zero must not render as a fall'
    ).not.toMatch(/↓\s*0%/);

    // The inverse mistake would be just as wrong, and is the obvious way to
    // "fix" this by accident.
    expect(
      strip,
      'a change of zero must not render as a rise either'
    ).not.toMatch(/↑\s*0%/);
  });

  test('nothing throws during the first render', async ({ page }) => {
    // BUG-043 threw nothing and logged nothing — it just quietly drew no pins.
    // This does not catch it. It is here so that the next defect of that shape,
    // which does throw, is not also found by eye.
    const failures: string[] = [];
    page.on('pageerror', (err) => failures.push(err.message));

    await page.goto('/');
    await settleMap(page);

    expect(failures, 'the dashboard threw during its first render').toEqual([]);
  });
});

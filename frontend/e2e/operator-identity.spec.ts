import fs from 'node:fs';
import path from 'node:path';
import type { APIRequestContext, Page } from '@playwright/test';
import { test, expect } from './fixtures';
import { API, OPERATOR_PASSWORD } from './env';
import { PERSONA_MARKERS, TELEMETRY_MARKERS, markersIn } from './invented';

/**
 * The operator the dashboard shows is the account the backend holds.
 *
 * Until 25 Sep every visitor was silently signed in as the commander and shown
 * as 'Rajesh K. Verma', a persona the page swapped in for the backend's own
 * name. That lived in an aria-label, the profile dropdown and the settings
 * drawer, where the page-load text scan in no-invented-data.spec.ts cannot see
 * it, so this spec opens each of them.
 *
 * It signs in as `commander` with the password `./start.sh e2e-backend` set in
 * indra_e2e (E2E_OPERATOR_PASSWORD, default 'indra-e2e-only').
 */

const SHOTS = path.join(__dirname, 'screenshots');
fs.mkdirSync(SHOTS, { recursive: true });

const USERNAME = 'commander';

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** GET /api/profile/me as the backend answers it for USERNAME. */
async function backendProfile(request: APIRequestContext) {
  const token = await request.post(`${API}/api/auth/token`, {
    form: { username: USERNAME, password: OPERATOR_PASSWORD },
  });
  expect(token.status(), `the E2E backend must accept ${USERNAME} / E2E_OPERATOR_PASSWORD`).toBe(200);
  const { access_token } = await token.json();
  const me = await request.get(`${API}/api/profile/me`, {
    headers: { Authorization: `Bearer ${access_token}` },
  });
  expect(me.status()).toBe(200);
  return me.json();
}

async function signIn(page: Page) {
  await page.getByLabel(/^Operator profile:/).click();
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Operator sign-in' });
  await dialog.getByLabel('Username').fill(USERNAME);
  await dialog.getByLabel('Password').fill(OPERATOR_PASSWORD);
  await dialog.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(dialog).toHaveCount(0);
}

test.describe('the signed-in operator is the account the backend holds', () => {
  test('the profile needs a token; ?user= names nobody', async ({ request }) => {
    expect((await request.get(`${API}/api/profile/me`)).status()).toBe(401);
    expect((await request.get(`${API}/api/profile/me?user=${USERNAME}`)).status()).toBe(401);
  });

  test('signed out, the chrome says so and names no one', async ({ page }) => {
    await page.goto('/');
    const trigger = page.getByLabel(/^Operator profile:/);
    await expect(trigger).toHaveAttribute('aria-label', 'Operator profile: Not signed in');
    await expect(page.getByLabel('Not signed in. Sign in')).toBeVisible();

    await trigger.click();
    await expect(page.getByTestId('session-status')).toHaveText('Not signed in');
    const body = await page.locator('body').innerText();
    expect(markersIn(body, PERSONA_MARKERS)).toEqual([]);
  });

  test('signed in, the name shown is /api/profile/me full_name', async ({ page, request }) => {
    const me = await backendProfile(request);
    expect(me.full_name, 'the commander account must have a name').toBeTruthy();

    await page.goto('/');
    await signIn(page);

    // The backend's name, unaltered: never swapped for a persona.
    const trigger = page.getByLabel(/^Operator profile:/);
    await expect(trigger).toHaveAttribute(
      'aria-label',
      new RegExp(`^Operator profile: ${escapeRegExp(me.full_name)}( \\(|$)`)
    );
    expect(await trigger.getAttribute('aria-label')).not.toContain('Rajesh K. Verma');

    await trigger.click();
    await expect(page.getByRole('heading', { level: 4, name: me.full_name, exact: true })).toBeVisible();
    await expect(page.getByTestId('session-status')).toContainText(`Signed in as ${USERNAME}`);
    await expect(page.getByRole('button', { name: 'Sign out', exact: true })).toBeVisible();
    await page.screenshot({ path: path.join(SHOTS, 'identity-01-signed-in.png') });

    // No role switcher: neither its labels nor its four persona buttons.
    const dropdown = await page.locator('body').innerText();
    expect(markersIn(dropdown, PERSONA_MARKERS), 'the dropdown shows a persona or the switcher').toEqual([]);
    await expect(page.getByRole('button', { name: 'Ops Lead', exact: true })).toHaveCount(0);

    // The profile page renders the same record, with no persona switcher.
    await page.goto('/profile');
    await expect(page.getByRole('heading', { level: 2, name: me.full_name, exact: true })).toBeVisible();
    const profile = await page.locator('body').innerText();
    expect(markersIn(profile, PERSONA_MARKERS), 'the profile page shows a persona or the switcher').toEqual([]);
    await page.screenshot({ path: path.join(SHOTS, 'identity-02-profile.png'), fullPage: true });
  });

  test('the settings drawer shows no invented telemetry', async ({ page }) => {
    await page.goto('/');
    await page.getByLabel('Platform Settings').click();
    await expect(page.getByLabel('Close settings drawer')).toBeVisible();
    await page.screenshot({ path: path.join(SHOTS, 'identity-03-settings-drawer.png') });

    const body = await page.locator('body').innerText();
    expect(markersIn(body, TELEMETRY_MARKERS), 'the drawer shows invented telemetry').toEqual([]);
  });
});

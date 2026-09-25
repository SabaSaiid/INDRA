import { test as base, expect } from '@playwright/test';
import { API } from './env';

/**
 * `test` for every spec: it fails a test in which the page sent an /api/ or
 * /ws/ request to any origin but the E2E backend's.
 *
 * global-setup.ts proves which backend E2E_API_URL is; this proves the page
 * under test talks to that one and no other, i.e. that the build really was
 * made with NEXT_PUBLIC_API_BASE_URL set to it.
 */

const API_ORIGIN = new URL(API).origin;
const WS_ORIGIN = API_ORIGIN.replace(/^http/, 'ws');

function isBackendPath(url: URL): boolean {
  return url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws/');
}

export const test = base.extend<{ onlyE2eBackend: void }>({
  onlyE2eBackend: [
    async ({ page }, use) => {
      const strays: string[] = [];
      page.on('request', (req) => {
        const url = new URL(req.url());
        if (isBackendPath(url) && url.origin !== API_ORIGIN) strays.push(req.url());
      });
      page.on('websocket', (ws) => {
        const url = new URL(ws.url());
        if (isBackendPath(url) && url.origin !== WS_ORIGIN) strays.push(ws.url());
      });

      await use();

      expect(strays, `the page called a backend other than ${API}`).toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };

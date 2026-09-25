/**
 * Where an E2E run points, and the rules the environment itself must satisfy.
 *
 * There is no default backend. The suite submits reports, so a default would
 * mean a forgotten variable writes probes into whatever answers on it — which is
 * how E2E probes once reached the dev database. `make e2e-backend` starts the
 * disposable backend on indra_e2e (port 8100) and `make e2e` sets these.
 *
 * Importing this module refuses a missing or unsafe E2E_API_URL, so the config
 * fails before Playwright builds anything. global-setup.ts then makes the
 * backend prove it is the E2E one.
 */

function refuse(reason: string): never {
  throw new Error(
    `E2E refused: ${reason}\n` +
      'Start the disposable backend with `make e2e-backend`, then run `make e2e`.'
  );
}

const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]']);

/** The E2E backend's base URL: set, loopback, and never the dev backend's :8000. */
function e2eApiUrl(): string {
  const raw = process.env.E2E_API_URL;
  if (!raw) refuse('E2E_API_URL is not set. There is no default backend.');

  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    refuse(`E2E_API_URL is not a URL: ${raw}`);
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    refuse(`E2E_API_URL must be http or https, not ${url.protocol}`);
  }
  if (!LOOPBACK_HOSTS.has(url.hostname)) {
    refuse(`E2E_API_URL must be a loopback host (localhost, 127.0.0.1, ::1), not ${url.hostname}.`);
  }
  if (url.port === '8000') {
    refuse('E2E_API_URL points at :8000, the dev backend. The E2E backend runs on :8100.');
  }
  return raw.replace(/\/+$/, '');
}

export const API = e2eApiUrl();

/** The database the E2E backend must report; a name not ending in _e2e is refused. */
export const EXPECT_DB = process.env.E2E_EXPECT_DB || 'indra_e2e';
if (!/_e2e$/.test(EXPECT_DB)) {
  refuse(`E2E_EXPECT_DB is '${EXPECT_DB}', which does not end in _e2e.`);
}

/** The port the E2E build of the dashboard is served on. */
export const PORT = 3100;
export const BASE = `http://localhost:${PORT}`;

/**
 * The password `./start.sh e2e-backend` sets on every account in indra_e2e.
 * The default exists only in that disposable database.
 */
export const OPERATOR_PASSWORD = process.env.E2E_OPERATOR_PASSWORD || 'indra-e2e-only';

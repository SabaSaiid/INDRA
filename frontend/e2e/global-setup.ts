import { API, EXPECT_DB } from './env';

/**
 * The suite runs only against a backend that proves it is the disposable E2E one.
 *
 * Refused unless:
 *   1. E2E_API_URL is set, is a loopback host and is not :8000 (env.ts, checked
 *      when the config loads, before the dashboard is built);
 *   2. GET /api/e2e/identity answers 200 with environment 'e2e', a database whose
 *      name ends in _e2e and equals E2E_EXPECT_DB (default indra_e2e), and the
 *      indra.e2e.* topic and indra-e2e-* consumer group. Only a backend started
 *      with ENVIRONMENT=e2e mounts that route; any other answers 404;
 *   3. /healthz reports the database up.
 *
 * Playwright starts the web server before this runs, but serving the build sends
 * nothing to the backend: no page is opened until every check here has passed.
 */

function refuse(reason: string): never {
  throw new Error(
    `E2E refused: ${reason}\n` +
      'Start the disposable backend with `make e2e-backend`, then run `make e2e`.'
  );
}

async function getJson(path: string): Promise<{ status: number; body: any }> {
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, { signal: AbortSignal.timeout(10_000) });
  } catch (err) {
    refuse(`cannot reach ${API}${path}: ${err instanceof Error ? err.message : err}`);
  }
  let body: any = null;
  try {
    body = await res.json();
  } catch {
    // Left null; the checks below say what was missing.
  }
  return { status: res.status, body };
}

export default async function globalSetup() {
  const identity = await getJson('/api/e2e/identity');
  if (identity.status === 404) {
    refuse(`${API} has no /api/e2e/identity, so it is not a backend started with ENVIRONMENT=e2e.`);
  }
  if (identity.status !== 200 || !identity.body) {
    refuse(`${API}/api/e2e/identity answered HTTP ${identity.status}.`);
  }
  const { environment, database, reports_topic, consumer_group } = identity.body;
  if (environment !== 'e2e') {
    refuse(`the backend says its environment is '${environment}', not 'e2e'.`);
  }
  if (typeof database !== 'string' || !/_e2e$/.test(database)) {
    refuse(`the backend's database is '${database}', which does not end in _e2e.`);
  }
  if (database !== EXPECT_DB) {
    refuse(`the backend's database is '${database}', but E2E_EXPECT_DB is '${EXPECT_DB}'.`);
  }
  if (typeof reports_topic !== 'string' || !reports_topic.startsWith('indra.e2e.')) {
    refuse(`the backend publishes reports to '${reports_topic}', not an indra.e2e.* topic.`);
  }
  if (typeof consumer_group !== 'string' || !consumer_group.startsWith('indra-e2e-')) {
    refuse(`the backend's consumer group is '${consumer_group}', not an indra-e2e-* group.`);
  }

  const health = await getJson('/healthz');
  const dbStatus = health.body?.checks?.database?.status;
  if (dbStatus !== 'up') {
    refuse(`/healthz reports the database as '${dbStatus ?? 'missing'}', not 'up'.`);
  }
}

/**
 * The one backend this build talks to: every fetch, the sign-in call and the
 * `/ws/events` socket. `next build` inlines NEXT_PUBLIC_API_BASE_URL, so a build
 * can never send some requests to one backend and the socket to another.
 */
export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000').replace(/\/+$/, '');

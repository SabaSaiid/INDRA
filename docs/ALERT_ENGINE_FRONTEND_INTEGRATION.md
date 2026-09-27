# Alert Engine Frontend Integration Audit

## 1. Existing Warnings Data Flow

The Warnings page (`frontend/src/app/alerts/page.tsx`) displays two distinct kinds of data:
1. **Official Warnings**: CAP alerts issued by IMD, CWC, and state SDMAs. These are fetched from the NDMA's SACHET feed by the backend poller. They are queried via `GET /api/alerts/agency`.
2. **INDRA Events**: HIGH or CRITICAL severity events derived from fused reports by the INDRA backend. These are queried via `GET /api/events` and include their actual human-review status.

The page uses React state (`agencyAlerts` and `events`) to manage this data, and formats them into uniform `WarningCard` objects for presentation. Real-time updates to INDRA events are handled via a WebSocket subscription (`useIndraWebSocket`).

## 2. Existing INDRA Event Data Flow

INDRA events are heavily processed by the backend. They carry:
- `review_status`: Actual operator review status (e.g., `PENDING_HUMAN_REVIEW`, `AUTO_PUBLISHED`, `HUMAN_APPROVED`, `QUARANTINED`).
- `severity`: Event severity classification.
- `confidence_score`: A numerical confidence metric.
- `quadrant`: Geographic placement or internal cluster reference.

The `safeEventState` helper determines the correct label to show based on the event's raw data. 

## 3. Where Alert Engine Data Will Be Added

The Alert Engine will be introduced as an entirely additive, independent system.
- It will NOT replace the `/api/alerts/agency` call or the `agencyAlerts` state.
- It will NOT intercept or alter the presentation of INDRA Events.
- It will have its own dedicated section on the Warnings page (e.g., an "INDRA Alert Engine" section), placed below the Official Warnings or alongside them.
- It will consume its own WebSocket and API endpoints from the Alert Engine service (e.g., port 8001) for its own `EngineAlert` data structure.

## 4. How Existing Data Will Remain Untouched

- The `page.tsx` file will be modified minimally to preserve the current state management (`agencyAlerts`, `events`), the filter logic (`selectedLevel`, `searchQuery`), and the `cards` memoization logic.
- The `return` block of the page will continue to map over the existing `filtered` cards to render the official warnings and INDRA events exactly as they appear today.
- A new sub-component or section will be appended to display `EngineAlert` objects retrieved from the Alert Engine.
- Any network failure connecting to the Alert Engine will only result in an "Alert Engine Offline" message *within its specific section*, ensuring the rest of the page remains fully functional.

## 5. Environment Configuration

The frontend currently uses `process.env.NEXT_PUBLIC_API_BASE_URL` to point to the backend API (`http://localhost:8000`).
For the Alert Engine, we will introduce:
- `NEXT_PUBLIC_ALERT_ENGINE_BASE_URL` (defaulting to `http://localhost:8001`)
- `NEXT_PUBLIC_ALERT_ENGINE_WS_URL` (defaulting to `ws://localhost:8001/ws/alerts`)

These variables will be used by the new API methods in `api.ts`. A local development fallback will be provided in code to ensure it works smoothly even if variables are missing. We will avoid hardcoded EC2 IPs.

## 6. Authentication Approach

The existing frontend issues JWTs via `POST /api/auth/token` using hardcoded demo credentials, relying on a `getAuthToken()` method that uses `localStorage` (persona switching).
The Alert Engine will reuse these tokens by requiring the `Authorization: Bearer <token>` header for any mutation (e.g., acknowledge, resolve). The Alert Engine will validate the JWT structure (without breaking if it simply trusts the caller for now, or validates the signature against the shared backend secret if available).

## 7. API Integration Approach

The `api.ts` file will be extended with new methods dedicated strictly to the Alert Engine:
- `fetchEngineAlerts()`: `GET /alerts`
- `acknowledgeEngineAlert()`: `POST /alerts/{id}/acknowledge`
- `resolveEngineAlert()`: `POST /alerts/{id}/resolve`
- `suppressEngineAlert()`: `POST /alerts/{id}/suppress`

These functions will be purely additive and append to the bottom of the file. No mock implementations will be created. If the Alert Engine is offline, the methods will return an empty array or throw an `ApiError` which will be handled gracefully by the UI section.

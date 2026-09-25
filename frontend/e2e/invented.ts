/**
 * Values removed from the dashboard on 25 Sep that more than one spec checks for.
 *
 * Compared ignoring case: the switcher's labels were rendered through a CSS
 * uppercase, and innerText returns them as shown.
 */

/**
 * The persona switcher: its invented operators, their badges, callsigns and
 * taglines, the invented email, and the switcher's own labels.
 *
 * Not 'Saba Saeed' or 'Meenal Sinha': they are real Team Sixth Sense members
 * and /teams lists them. Only the government titles invented for them are here.
 */
export const PERSONA_MARKERS = [
  'Rajesh K. Verma',
  'Vikram Sethi',
  'SEOC-PAT-091',
  'IMD-MET-552',
  'NDMA-DIR-001',
  'CIT-REP-06',
  'SEOC Bihar / NDMA',
  'IMD Nowcasting Cell',
  'NDMA National Grid',
  'Community Weather Watch',
  'Bayesian prior synthesis',
  'Doppler radar calibration',
  // 0018 cleared the seeded PATNA-ACTUAL; the rest were frontend fallbacks.
  'PATNA-ACTUAL',
  'SIGNAL-IMD',
  'NDMA-CONTROL',
  'GROUND-01',
  'sih-indra.gov.in',
  'SIH RBAC DEMO',
  'Switch Role',
  'Select Active Persona',
  'RBAC Identity Testing',
  'Demo account',
  'Secure Session (JWT HS256)',
];

/** The settings page and drawer's weather-station readout that no station sent. */
export const TELEMETRY_MARKERS = [
  'Patna Station #04',
  'Calculated Weather Station Output',
  'Live Telemetry Output Sample',
  'Telemetry live',
  'LIVE SYNC ACTIVE',
];

/** The markers from `markers` that `text` contains, ignoring case. */
export function markersIn(text: string, markers: readonly string[]): string[] {
  const lower = text.toLowerCase();
  return markers.filter((m) => lower.includes(m.toLowerCase()));
}

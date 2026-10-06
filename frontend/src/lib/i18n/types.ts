// frontend/src/lib/i18n/types.ts
// Strict TypeScript interfaces for the INDRA translation system.
// All language dictionaries MUST satisfy the TranslationDict interface.

export type SupportedLanguage =
  | 'en' | 'hi' | 'bn' | 'te' | 'ta'
  | 'mr' | 'or' | 'gu' | 'kn' | 'ml'
  | 'pa' | 'as' | 'ur';

export interface LanguageMeta {
  code: SupportedLanguage;
  name: string;        // English name
  nativeName: string;  // Name in native script
  dir: 'ltr' | 'rtl';
  fontFamily: string;  // Noto Sans variant for this script
}

export const SUPPORTED_LANGUAGES: Record<SupportedLanguage, LanguageMeta> = {
  en: { code: 'en', name: 'English',    nativeName: 'English',     dir: 'ltr', fontFamily: 'Public Sans, sans-serif' },
  hi: { code: 'hi', name: 'Hindi',      nativeName: 'हिन्दी',        dir: 'ltr', fontFamily: '"Noto Sans Devanagari", sans-serif' },
  bn: { code: 'bn', name: 'Bengali',    nativeName: 'বাংলা',         dir: 'ltr', fontFamily: '"Noto Sans Bengali", sans-serif' },
  te: { code: 'te', name: 'Telugu',     nativeName: 'తెలుగు',        dir: 'ltr', fontFamily: '"Noto Sans Telugu", sans-serif' },
  ta: { code: 'ta', name: 'Tamil',      nativeName: 'தமிழ்',         dir: 'ltr', fontFamily: '"Noto Sans Tamil", sans-serif' },
  mr: { code: 'mr', name: 'Marathi',    nativeName: 'मराठी',         dir: 'ltr', fontFamily: '"Noto Sans Devanagari", sans-serif' },
  or: { code: 'or', name: 'Odia',       nativeName: 'ଓଡ଼ିଆ',          dir: 'ltr', fontFamily: '"Noto Sans Oriya", sans-serif' },
  gu: { code: 'gu', name: 'Gujarati',   nativeName: 'ગુજરાતી',       dir: 'ltr', fontFamily: '"Noto Sans Gujarati", sans-serif' },
  kn: { code: 'kn', name: 'Kannada',    nativeName: 'ಕನ್ನಡ',         dir: 'ltr', fontFamily: '"Noto Sans Kannada", sans-serif' },
  ml: { code: 'ml', name: 'Malayalam',  nativeName: 'മലയാളം',        dir: 'ltr', fontFamily: '"Noto Sans Malayalam", sans-serif' },
  pa: { code: 'pa', name: 'Punjabi',    nativeName: 'ਪੰਜਾਬੀ',        dir: 'ltr', fontFamily: '"Noto Sans Gurmukhi", sans-serif' },
  as: { code: 'as', name: 'Assamese',   nativeName: 'অসমীয়া',        dir: 'ltr', fontFamily: '"Noto Sans Bengali", sans-serif' },
  ur: { code: 'ur', name: 'Urdu',       nativeName: 'اردو',          dir: 'ltr', fontFamily: '"Noto Sans Arabic", "Noto Nastaliq Urdu", sans-serif' },
};

// ─────────────────────────────────────────────────────────────────────────────
// Master translation dictionary schema — every key must exist in en.ts
// ─────────────────────────────────────────────────────────────────────────────
export interface TranslationDict {
  nav: {
    // Sidebar navigation
    dashboard: string;
    live_map: string;
    incident_events: string;
    field_reports: string;
    official_warnings: string;
    analytics: string;
    response_teams: string;
    admin_panel: string;
    system_settings: string;
    platform_settings: string;
    // Section headers
    section_tactical: string;
    section_intelligence: string;
    section_command: string;
    // Topbar
    search_placeholder: string;
    report_incident: string;
    notifications: string;
    telemetry_live: string;
    operator: string;
    // Additional navigation items
    geospatial_feeds?: string;
    early_warnings?: string;
    teams_hub?: string;
    operator_profile?: string;
    admin_command?: string;
  };

  kpis: {
    active_events: string;
    quarantined: string;
    reports_24h: string;
    stations_active: string;
    official_warnings: string;
    avg_confidence: string;
    grid_live: string;
    system_healthy: string;
    live_label: string;
    updated_label: string;
    // KPI tile labels matching api.ts fetchDashboardSummary IDs
    total_reports: string;
    verified_events: string;
    critical_events: string;
    citizen_reports: string;
    awaiting_review: string;
    active_alerts: string;
    // KPI delta labels
    delta_last_24h: string;
    delta_review_queue: string;
    delta_in_force: string;
  };

  chart: {
    by_hazard: string;
    by_severity: string;
    events: string;
    warnings: string;
    in_force_now: string;
    no_events_range: string;
    no_warnings_force: string;
    scroll_more: string;
    live_from_api: string;
  };

  hazards: {
    URBAN_FLOOD: string;
    HEAVY_RAIN: string;
    THUNDERSTORM: string;
    CYCLONE: string;
    HEATWAVE: string;
    COLDWAVE: string;
    DUST_STORM: string;
    FOG: string;
    LANDSLIDE: string;
    AVALANCHE: string;
    EARTHQUAKE: string;
    TSUNAMI: string;
    DROUGHT: string;
    LIGHTNING: string;
    UNKNOWN: string;
  };

  severity: {
    CRITICAL: string;
    HIGH: string;
    MODERATE: string;
    LOW: string;
    ADVISORY: string;
  };

  status: {
    AUTO_VERIFIED: string;
    PENDING_HUMAN_REVIEW: string;
    QUARANTINED: string;
    HUMAN_APPROVED: string;
    HUMAN_REJECTED: string;
  };

  map: {
    title: string;
    basemap_dark: string;
    basemap_satellite: string;
    basemap_topo: string;
    basemap_street: string;
    layer_event_radius: string;
    layer_weather_stations: string;
    layer_sachet_warnings: string;
    layer_h3_grid: string;
    events_on_map: string;
    loading: string;
  };

  receipt: {
    title: string;
    subtitle: string;
    factor_weather: string;
    factor_citizen: string;
    factor_proximity: string;
    factor_source: string;
    factor_image: string;
    factor_historical: string;
    commander_review: string;
    approve_btn: string;
    reject_btn: string;
    confidence_label: string;
    sources_label: string;
    close: string;
  };

  common: {
    loading: string;
    error: string;
    retry: string;
    close: string;
    save: string;
    cancel: string;
    confirm: string;
    yes: string;
    no: string;
    na: string;
    view_all: string;
    see_more: string;
    ago: string;
    just_now: string;
    minutes_ago: string;
    hours_ago: string;
    today: string;
    yesterday: string;
    duty_on: string;
    duty_off: string;
    duty_standby: string;
    duty_deployed: string;
    secure_session: string;
    session_inactive: string;
    radio_designation: string;
    switch_role: string;
  };

  dashboard: {
    welcome_title: string;
    welcome_subtitle: string;
    mission_control: string;
    recent_events: string;
    event_distribution: string;
    live_feed: string;
    no_events: string;
    no_reports: string;
  };
}

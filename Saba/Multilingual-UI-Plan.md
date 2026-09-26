# 🌐 Flawless Multilingual UI Implementation Plan: Hindi & Major Regional Languages

**Document Date:** 26 September 2026  
**Author / Team:** Saba Saeed • Team Sixth Sense  
**Project:** INDRA (*Intelligent National Disaster & Weather Platform*)  
**Git Branch:** `26-sep-lang-ui`  
**Target:** Client-Side Zero-Backend-Impact Multilingual Architecture  

---

## 🏛️ Executive Summary & Guiding Principles

This plan provides an end-to-end engineering blueprint for introducing full **Multilingual UI localization** across **Hindi and 11 major Indian regional languages** in INDRA, while adhering to one strict non-negotiable constraint:

> ⚠️ **STRICT CODE ISOLATION RULE: ZERO BACKEND CHANGES.**  
> The FastAPI backend, database schemas, API contracts, enums, workers, and Redpanda streams will remain **100% untouched**. All localization, script rendering, dynamic enum mapping, and localized date/number formatting will execute strictly within the **Next.js 14 client layer**.

---

## 🗺️ 1. Supported Languages Matrix (12 Indian Regional Languages)

To achieve parity with India's national disaster standards (matching NDMA SACHET), the following 12 languages will be supported:

| # | Language Code | English Name | Native Script | Primary Regional Focus & Disaster Context |
| :-: | :---: | :--- | :--- | :--- |
| **1** | `en` | English *(Base)* | English | National Command, NDRF HQ, Pan-India Analysts |
| **2** | `hi` | Hindi | **हिन्दी** | National Official Language, North & Central India (Bihar, UP, MP) |
| **3** | `bn` | Bengali | **বাংলা** | West Bengal, Tripura, coastal cyclone & delta floods |
| **4** | `te` | Telugu | **తెలుగు** | Andhra Pradesh & Telangana, Bay of Bengal cyclones |
| **5** | `ta` | Tamil | **தமிழ்** | Tamil Nadu, NE Monsoon cloudbursts & coastal surges |
| **6** | `mr` | Marathi | **मराठी** | Maharashtra, Mumbai urban flooding, Western Ghats landslides |
| **7** | `or` | Odia | **ଓଡ଼ିଆ** | Odisha, high-frequency cyclone landfall & Mahanadi floods |
| **8** | `gu` | Gujarati | **ગુજરાતી** | Gujarat, Arabian Sea cyclones, Kutch inundations & heatwaves |
| **9** | `kn` | Kannada | **ಕನ್ನಡ** | Karnataka, Bengaluru urban flooding, Western Ghats |
| **10**| `ml` | Malayalam | **മലയാളം** | Kerala, flash floods, extreme rain & debris flows |
| **11**| `pa` | Punjabi | **ਪੰਜਾਬੀ** | Punjab, Sutlej/Beas river floods & seasonal heatwaves |
| **12**| `as` | Assamese | **অসমীয়া** | Assam, Brahmaputra riverine flooding & annual inundation |

---

## 📐 2. Architecture & Design Pattern

### Why Client-Side Context Beats Subpath Routing (`/hi/...`) for INDRA
* Next.js subpath routing (`/hi/events`, `/te/live-map`) would require rewriting all 14 page directories, creating route middleware redirects, and breaking existing internal links and WebSocket paths.
* **Our Flawless Architecture:** A **Type-Safe React Context + Custom Hook (`useTranslation`)**:
  1. Instant client-side language switching without page reloads or layout re-renders.
  2. Preserves all URLs (`/`, `/live-map`, `/events`, `/reports`).
  3. Seamless persistence via `localStorage` (`indra_user_language`).
  4. Automatic fallback to English (`en`) if a translation key is missing in a regional dialect.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                               CLIENT-SIDE I18N PIPELINE                                │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 1. FastAPI Backend (JSON)                                                              │
│    └─► { "event_type": "URBAN_FLOOD", "severity": "CRITICAL", "confidence": 0.85 }    │
│                                                                                        │
│ 2. Frontend LanguageContext                                                            │
│    ├─► Active Language: "hi" (Persisted in localStorage)                               │
│    └─► Type-Safe Translation Dictionary: locales/hi.ts                                 │
│                                                                                        │
│ 3. React Components (via useTranslation())                                             │
│    ├─► t('nav.live_map')           ──► "लाइव सामरिक मानचित्र"                          │
│    ├─► t.hazard(event.event_type)   ──► "शहरी बाढ़"                                    │
│    ├─► t.severity(event.severity)   ──► "अत्यधिक गंभीर"                                │
│    └─► t.formatDate(event.time)     ──► "२४ सितम्बर २०२६, शाम ५:३०"                    │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 📁 3. File Structure & Directory Layout

All translation logic is organized inside `frontend/src/lib/i18n/`:

```
frontend/src/lib/i18n/
├── index.ts                      # Main exports & singleton helpers
├── types.ts                      # Strict TypeScript interfaces for all translation keys
├── LanguageContext.tsx           # React Context Provider wrapping the application
├── useTranslation.ts             # Custom hook used across components
├── formatters.ts                 # Localized date, time, and number utilities (Intl API)
└── locales/                      # Modular translation dictionaries
    ├── en.ts                     # Single Source of Truth (English base)
    ├── hi.ts                     # Hindi (हिन्दी)
    ├── bn.ts                     # Bengali (বাংলা)
    ├── te.ts                     # Telugu (తెలుగు)
    ├── ta.ts                     # Tamil (தமிழ்)
    ├── mr.ts                     # Marathi (मराठी)
    ├── or.ts                     # Odia (ଓଡ଼ିଆ)
    ├── gu.ts                     # Gujarati (ગુજરાતી)
    ├── kn.ts                     # Kannada (ಕನ್ನಡ)
    ├── ml.ts                     # Malayalam (മലയാളം)
    ├── pa.ts                     # Punjabi (ਪੰਜਾਬੀ)
    └── as.ts                     # Assamese (অসমীয়া)
```

---

## 🔍 4. Translation Schema & Grouped Namespaces (`types.ts`)

To ensure **100% type safety and zero missing keys**, the translation schema is broken into distinct namespaces:

### 1. `nav`: Navigation & Headers
* Sidebar navigation items (`dashboard`, `live_map`, `incident_events`, `field_reports`, `official_warnings`, `analytics`, `response_teams`, `admin_panel`, `system_settings`).
* Topbar actions (`submit_report`, `search_placeholder`, `notifications`, `operator_duty`, `on_duty`, `off_duty`).

### 2. `kpis`: Mission Control Metrics
* Metrics strip (`active_events`, `quarantined`, `reports_24h`, `stations_active`, `official_warnings`, `avg_confidence`, `grid_live`, `system_healthy`).

### 3. `hazards`: Standard Disaster Enums
Dynamic mapping from backend enum to localized string:
* `URBAN_FLOOD` $\rightarrow$ *"शहरी बाढ़"* (HI) / *"పట్టణ వరదలు"* (TE)
* `HEAVY_RAIN` $\rightarrow$ *"भारी वर्षा"* (HI) / *"భారీ వర్షం"* (TE)
* `THUNDERSTORM` $\rightarrow$ *"तूफ़ान एवं बिजली"* (HI) / *"ఉరుములతో కూడిన తుఫాను"* (TE)
* `CYCLONE` $\rightarrow$ *"चक्रवात"* (HI) / *"తుఫాను"* (TE)
* `HEATWAVE` $\rightarrow$ *"लू / अत्यधिक गर्मी"* (HI) / *"తీవ్ర వడగాల్పులు"* (TE)
* `COLDWAVE` $\rightarrow$ *"शीतलहर"* (HI) / *"చలిగాలులు"* (TE)
* `DUST_STORM` $\rightarrow$ *"धूल भरी आँधी"* (HI) / *"ధూళి తుఫాను"* (TE)
* `FOG` $\rightarrow$ *"घना कोहरा"* (HI) / *"పొగమంచు"* (TE)
* `LANDSLIDE` $\rightarrow$ *"भूस्खलन"* (HI) / *"కొండచరియలు విరిగిపడటం"* (TE)
* `AVALANCHE` $\rightarrow$ *"हिमस्खलन"* (HI) / *"హిమపాతం"* (TE)

### 4. `severity`: Threat Levels
* `CRITICAL` $\rightarrow$ *"अत्यधिक गंभीर"* (HI)
* `HIGH` $\rightarrow$ *"गंभीर"* (HI)
* `MODERATE` $\rightarrow$ *"मध्यम"* (HI)
* `LOW` / `ADVISORY` $\rightarrow$ *"सलाहकार / सामान्य"* (HI)

### 5. `status`: Pipeline & Review States
* `AUTO_VERIFIED` $\rightarrow$ *"स्वतः सत्यापित"*
* `PENDING_HUMAN_REVIEW` $\rightarrow$ *"मानव समीक्षा लंबित"*
* `QUARANTINED` $\rightarrow$ *"संदेहास्पद / अलग रखा गया"*
* `HUMAN_APPROVED` $\rightarrow$ *"कमांड द्वारा अनुमोदित"*
* `HUMAN_REJECTED` $\rightarrow$ *"अस्वीकृत"*

### 6. `receipt`: The Verification Receipt Modal
* 6 Factors: *"मौसम सहमति"*, *"स्वतंत्र नागरिक रिपोर्टें"*, *"स्थान एवं समय निकटता"*, *"स्रोत विश्वसनीयता"*, *"छवि विश्लेषण"*, *"ऐतिहासिक असंगति"*.
* Factors explanations and commander review buttons.

### 7. `map`: Tactical Map Controls
* Basemap options: *"डार्क मोड"*, *"उपग्रह दृश्य"*, *"स्थलाकृतिक"*, *"सड़क दृश्य"*.
* Layers: *"घटना परिधि"*, *"मौसम स्टेशन"*, *"सचेत चेतावनियां"*, *"एच3 ग्रिड"*.

---

## 🛠️ 5. Implementation Blueprints: Code Specifications

### Blueprint 1: The `useTranslation` Hook Specification

```typescript
// frontend/src/lib/i18n/useTranslation.ts
'use client';

import { useContext } from 'react';
import { LanguageContext } from './LanguageContext';
import { en } from './locales/en';
import { translations } from './index';
import type { SupportedLanguage } from './types';

export function useTranslation() {
  const context = useContext(LanguageContext);
  if (!context) {
    throw new Error('useTranslation must be used within a LanguageProvider');
  }

  const { language, setLanguage } = context;
  const currentDict = translations[language] || en;

  // Translation lookup with automatic English fallback
  function t(keyPath: string): string {
    const keys = keyPath.split('.');
    let result: any = currentDict;
    for (const k of keys) {
      result = result?.[k];
      if (result === undefined) break;
    }
    if (result !== undefined && typeof result === 'string') return result;

    // Fallback to English
    let fallback: any = en;
    for (const k of keys) {
      fallback = fallback?.[k];
      if (fallback === undefined) break;
    }
    return typeof fallback === 'string' ? fallback : keyPath;
  }

  // Dynamic Enum Formatters
  t.hazard = (hazardType?: string) => t(`hazards.${hazardType || 'UNKNOWN'}`);
  t.severity = (severityLevel?: string) => t(`severity.${severityLevel || 'LOW'}`);
  t.status = (reviewStatus?: string) => t(`status.${reviewStatus || 'QUARANTINED'}`);

  return { t, language, setLanguage };
}
```

---

### Blueprint 2: Topbar Language Switcher UI Component

A sleek, tactile dropdown component with native scripts integrated into [`frontend/src/components/Topbar.tsx`](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/frontend/src/components/Topbar.tsx):

```tsx
// LanguagePicker.tsx
import { Globe } from 'lucide-react';
import { useTranslation } from '@/lib/i18n/useTranslation';
import { SUPPORTED_LANGUAGES } from '@/lib/i18n/types';

export default function LanguagePicker() {
  const { language, setLanguage } = useTranslation();

  return (
    <div className="relative">
      <DropdownMenu>
        <DropdownMenuTrigger className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-border bg-paper-light text-ink hover:bg-paper-dark transition-colors">
          <Globe className="w-4 h-4 text-accent-cyan" />
          <span className="text-xs font-medium font-sans">
            {SUPPORTED_LANGUAGES[language].nativeName}
          </span>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-48 bg-paper border border-border shadow-xl rounded-xl p-1">
          {Object.entries(SUPPORTED_LANGUAGES).map(([code, lang]) => (
            <DropdownMenuItem
              key={code}
              onClick={() => setLanguage(code as any)}
              className={`flex items-center justify-between px-3 py-2 text-xs rounded-lg cursor-pointer ${
                language === code ? 'bg-accent-cyan/10 text-accent-cyan font-semibold' : 'text-ink hover:bg-paper-light'
              }`}
            >
              <span>{lang.nativeName}</span>
              <span className="text-[10px] text-ink-muted uppercase">{lang.name}</span>
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
```

---

### Blueprint 3: Native Typography & Font Rendering

To render complex Indian scripts (Devanagari, Bengali, Telugu, Tamil) with extreme sharpness and correct typographic ligatures, add Google Noto Sans Indian font subsets to [`frontend/src/app/layout.tsx`](file:///Users/sabasaeed/0_Saba%20CSE/Hackathons/SIH%2026/INDRA/frontend/src/app/layout.tsx):

```html
<link
  href="https://fonts.googleapis.com/css2?family=Noto+Sans+Bengali:wght@400;500;600;700&family=Noto+Sans+Devanagari:wght@400;500;600;700&family=Noto+Sans+Gujarati:wght@400;500;600;700&family=Noto+Sans+Kannada:wght@400;500;600;700&family=Noto+Sans+Malayalam:wght@400;500;600;700&family=Noto+Sans+Oriya:wght@400;500;600;700&family=Noto+Sans+Tamil:wght@400;500;600;700&family=Noto+Sans+Telugu:wght@400;500;600;700&family=Noto+Sans:wght@400;500;600;700&display=swap"
  rel="stylesheet"
/>
```

And update `font-family` fallbacks in `frontend/tailwind.config.ts`:
```typescript
fontFamily: {
  sans: [
    'Public Sans',
    'Noto Sans Devanagari',
    'Noto Sans Bengali',
    'Noto Sans Telugu',
    'Noto Sans Tamil',
    'sans-serif',
  ],
}
```

---

## 📋 6. Step-by-Step Execution Plan

```
                              SPRINT ROADMAP
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ STEP 1: CREATE CORE I18N MODULE                                                        │
│ • Write types.ts, LanguageContext.tsx, useTranslation.ts                               │
│ • Wrap RootLayout with <LanguageProvider>                                              │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ STEP 2: BUILD DICTIONARIES (ENGLISH & HINDI FIRST)                                     │
│ • Author locales/en.ts (Source of Truth)                                               │
│ • Author locales/hi.ts (Complete Hindi translation)                                    │
│ • Author locales/te.ts, locales/bn.ts, locales/ta.ts, locales/mr.ts, etc.              │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ STEP 3: INTEGRATE TOPBAR & SETTINGS PICKER                                             │
│ • Add LanguagePicker to Topbar.tsx beside the Operator Persona switcher                │
│ • Add language selector to SettingsDrawer.tsx                                          │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ STEP 4: WIRE COMPONENTS TO useTranslation()                                            │
│ • Sidebar.tsx (All navigation links)                                                   │
│ • WelcomeHeader.tsx (Greeting, Status Strip, Mission Control toggles)                  │
│ • KpiCard.tsx (All tile headers)                                                       │
│ • RecentEventsList.tsx & EventDistributionChart.tsx                                    │
│ • EventVerificationModal.tsx (The Verification Receipt & 6 factors)                   │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ STEP 5: VERIFICATION & COMPILER AUDIT                                                  │
│ • Run `tsc --noEmit` to guarantee 0 TypeScript errors                                  │
│ • Run `next build` to verify production bundling                                       │
│ • Validate persistent selection via browser refresh                                    │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🎯 7. Pitch Line for SIH Judges
> *"While disaster alerts originate from central authorities, crisis response happens in the villages and districts of India. By deploying a zero-backend-impact multilingual architecture supporting 12 Indian regional languages with native Noto Sans typography, INDRA ensures that field commanders, local administrators, and citizens receive actionable disaster intelligence in their mother tongue in real time."*

---

*Plan prepared for SIH 2026 Implementation • Team Sixth Sense • Branch `26-sep-lang-ui`*

'use client';

import React, { useState } from 'react';
import {
  Eye,
  CheckCircle2,
  AlertTriangle,
  AlertOctagon,
  Info,
  ShieldCheck,
  Clock,
  Sparkles,
  Sliders,
  Maximize2,
  Columns,
  Layers,
  ArrowRight,
  Flame,
  CloudRain,
  Wind,
  Sun,
  Compass,
} from 'lucide-react';
import Sidebar from '@/components/Sidebar';
import Topbar from '@/components/Topbar';
import { useSidebar } from '@/lib/useSidebar';
import { useSettings } from '@/lib/useSettings';
import { THEME_REGISTRY, type ThemeId } from '@/lib/theme-registry';

type CvdType = 'normal' | 'protanopia' | 'deuteranopia' | 'tritanopia' | 'achromatopsia';

interface CvdDefinition {
  id: CvdType;
  label: string;
  sublabel: string;
  description: string;
  prevalence: string;
  filterId: string | null;
}

const CVD_MODES: CvdDefinition[] = [
  {
    id: 'normal',
    label: 'Standard Vision',
    sublabel: 'Trichromacy',
    description: 'Standard operational perception with all three cone photopigments intact.',
    prevalence: 'Default',
    filterId: null,
  },
  {
    id: 'protanopia',
    label: 'Protanopia',
    sublabel: 'Red-Blind / L-Cone Absent',
    description: 'Long-wavelength sensitivity absent. Saturated red shifts toward dark olive/khaki; amber and green converge.',
    prevalence: '~1.0% of males',
    filterId: 'cvd-protanopia',
  },
  {
    id: 'deuteranopia',
    label: 'Deuteranopia',
    sublabel: 'Green-Blind / M-Cone Absent',
    description: 'Medium-wavelength sensitivity absent. Green and amber converge; red and yellow lose hue distinction.',
    prevalence: '~5.0% of males',
    filterId: 'cvd-deuteranopia',
  },
  {
    id: 'tritanopia',
    label: 'Tritanopia',
    sublabel: 'Blue-Blind / S-Cone Absent',
    description: 'Short-wavelength sensitivity absent. Blue and green converge; yellow appears as pink/light violet.',
    prevalence: '~0.01% of population',
    filterId: 'cvd-tritanopia',
  },
  {
    id: 'achromatopsia',
    label: 'Achromatopsia',
    sublabel: 'Total Monochromacy / Luminance Only',
    description: 'Complete absence of color perception. All information must be distinguished strictly via luminance, typography, borders, and iconography.',
    prevalence: '~0.003% (Rare)',
    filterId: 'cvd-achromatopsia',
  },
];

export default function ColorVisionSimulatorPage() {
  const { isCollapsed } = useSidebar();
  const { settings, updateSetting } = useSettings();
  const [selectedCvd, setSelectedCvd] = useState<CvdType>('normal');
  const [viewLayout, setViewLayout] = useState<'matrix' | 'focused'>('matrix');
  const [globalFilterEnabled, setGlobalFilterEnabled] = useState(false);

  const activeTheme = THEME_REGISTRY[settings.themeMode] || THEME_REGISTRY.dark;
  const activeCvd = CVD_MODES.find((m) => m.id === selectedCvd) || CVD_MODES[0];

  return (
    <div
      className={`min-h-screen bg-surface-bg text-text transition-colors duration-200 ${
        globalFilterEnabled && activeCvd.filterId ? `filter-[url(#${activeCvd.filterId})]` : ''
      }`}
      style={
        globalFilterEnabled && activeCvd.filterId
          ? { filter: `url(#${activeCvd.filterId})` }
          : undefined
      }
    >
      {/* ── SVG Color Matrix Filters Definition ────────────────────── */}
      <svg aria-hidden="true" className="pointer-events-none absolute -top-[9999px] -left-[9999px] h-0 w-0">
        <defs>
          {/* Protanopia (Machado / Brettel standard) */}
          <filter id="cvd-protanopia" colorInterpolationFilters="sRGB">
            <feColorMatrix
              type="matrix"
              values="0.56667 0.43333 0 0 0
                      0.55833 0.44167 0 0 0
                      0       0.24167 0.75833 0 0
                      0       0       0       1 0"
            />
          </filter>

          {/* Deuteranopia (Machado / Brettel standard) */}
          <filter id="cvd-deuteranopia" colorInterpolationFilters="sRGB">
            <feColorMatrix
              type="matrix"
              values="0.625   0.375   0       0 0
                      0.7     0.3     0       0 0
                      0       0.3     0.7     0 0
                      0       0       0       1 0"
            />
          </filter>

          {/* Tritanopia (Machado / Brettel standard) */}
          <filter id="cvd-tritanopia" colorInterpolationFilters="sRGB">
            <feColorMatrix
              type="matrix"
              values="0.95    0.05    0       0 0
                      0       0.43333 0.56667 0 0
                      0       0.475   0.525   0 0
                      0       0       0       1 0"
            />
          </filter>

          {/* Achromatopsia (Photopic Luminance ITU-R BT.709) */}
          <filter id="cvd-achromatopsia" colorInterpolationFilters="sRGB">
            <feColorMatrix
              type="matrix"
              values="0.299   0.587   0.114   0 0
                      0.299   0.587   0.114   0 0
                      0.299   0.587   0.114   0 0
                      0       0       0       1 0"
            />
          </filter>
        </defs>
      </svg>

      <Sidebar />
      <Topbar />

      <main
        className={`transition-all duration-300 pt-16 p-6 min-h-screen ${
          isCollapsed ? 'ml-16' : 'ml-64'
        }`}
      >
        <div className="max-w-7xl mx-auto space-y-6">
          {/* Header */}
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-surface-border">
            <div>
              <div className="flex items-center gap-2.5">
                <span className="p-2 rounded-lg bg-surface-raised border border-surface-border text-brand">
                  <Eye className="w-5 h-5" />
                </span>
                <div>
                  <h1 className="text-xl font-bold tracking-tight text-text">
                    Color Vision Deficiency (CVD) Validation Lab
                  </h1>
                  <p className="text-xs text-text-secondary mt-0.5">
                    Real-time operational chromatic audit simulating photopigment deficiencies across INDRA&apos;s 5 interface themes.
                  </p>
                </div>
              </div>
            </div>

            {/* Global Quick Controls */}
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex items-center gap-1.5 p-1 bg-surface-raised rounded-lg border border-surface-border text-xs">
                <button
                  type="button"
                  onClick={() => setViewLayout('matrix')}
                  className={`flex items-center gap-1 px-2.5 py-1 rounded transition-colors ${
                    viewLayout === 'matrix'
                      ? 'bg-brand text-brand-contrast font-medium'
                      : 'text-text-secondary hover:text-text'
                  }`}
                >
                  <Columns className="w-3.5 h-3.5" />
                  Comparative Matrix
                </button>
                <button
                  type="button"
                  onClick={() => setViewLayout('focused')}
                  className={`flex items-center gap-1 px-2.5 py-1 rounded transition-colors ${
                    viewLayout === 'focused'
                      ? 'bg-brand text-brand-contrast font-medium'
                      : 'text-text-secondary hover:text-text'
                  }`}
                >
                  <Maximize2 className="w-3.5 h-3.5" />
                  Focused View
                </button>
              </div>

              <button
                type="button"
                onClick={() => setGlobalFilterEnabled(!globalFilterEnabled)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-medium transition-colors ${
                  globalFilterEnabled
                    ? 'bg-brand text-brand-contrast border-brand'
                    : 'bg-surface-raised border-surface-border text-text hover:border-brand/40'
                }`}
                title="Apply selected deficiency filter to the entire INDRA page container"
              >
                <Sliders className="w-3.5 h-3.5" />
                Global Page Filter: {globalFilterEnabled ? 'ON' : 'OFF'}
              </button>
            </div>
          </div>

          {/* Theme Selector Strip */}
          <div className="p-4 rounded-xl bg-surface-card border border-surface-border space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold tracking-wider uppercase text-text-secondary">
                Active Theme Under Test
              </span>
              <span className="text-xs text-text-secondary font-mono">
                Active: {activeTheme.label} ({settings.themeMode})
              </span>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
              {(Object.keys(THEME_REGISTRY) as ThemeId[]).map((tId) => {
                const item = THEME_REGISTRY[tId];
                const isSelected = settings.themeMode === tId;
                return (
                  <button
                    key={tId}
                    type="button"
                    onClick={() => updateSetting('themeMode', tId)}
                    className={`relative p-3 rounded-lg border text-left transition-all ${
                      isSelected
                        ? 'border-brand bg-brand/5 shadow-sm'
                        : 'border-surface-border bg-surface-raised hover:border-surface-border-strong'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-medium text-text">{item.label}</span>
                      {isSelected && (
                        <span className="w-2 h-2 rounded-full bg-brand" />
                      )}
                    </div>
                    {/* Swatch chip quad */}
                    <div className="flex items-center gap-1">
                      <span
                        className="w-4 h-4 rounded-full border border-black/10 dark:border-white/10"
                        style={{ backgroundColor: item.swatches.rail }}
                        title="Rail"
                      />
                      <span
                        className="w-4 h-4 rounded-full border border-black/10 dark:border-white/10"
                        style={{ backgroundColor: item.swatches.surface }}
                        title="Surface"
                      />
                      <span
                        className="w-4 h-4 rounded-full border border-black/10 dark:border-white/10"
                        style={{ backgroundColor: item.swatches.brand }}
                        title="Brand"
                      />
                      <span
                        className="w-4 h-4 rounded-full border border-black/10 dark:border-white/10"
                        style={{ backgroundColor: item.swatches.critical }}
                        title="Critical"
                      />
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Focused Selector (if focused layout active) */}
          {viewLayout === 'focused' && (
            <div className="flex flex-wrap items-center gap-2 p-2 bg-surface-card rounded-xl border border-surface-border">
              {CVD_MODES.map((mode) => {
                const isSelected = selectedCvd === mode.id;
                return (
                  <button
                    key={mode.id}
                    type="button"
                    onClick={() => setSelectedCvd(mode.id)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                      isSelected
                        ? 'bg-brand text-brand-contrast'
                        : 'text-text-secondary hover:text-text hover:bg-surface-raised'
                    }`}
                  >
                    {mode.label} <span className="opacity-70 text-[10px]">({mode.prevalence})</span>
                  </button>
                );
              })}
            </div>
          )}

          {/* Specimen Presentation */}
          {viewLayout === 'matrix' ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
              {CVD_MODES.map((mode) => (
                <div
                  key={mode.id}
                  className="rounded-xl border border-surface-border bg-surface-card flex flex-col overflow-hidden shadow-sm"
                >
                  {/* Card Header */}
                  <div className="p-3.5 bg-surface-raised border-b border-surface-border flex items-start justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-bold text-text">{mode.label}</span>
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-bg border border-surface-border text-text-secondary font-mono">
                          {mode.prevalence}
                        </span>
                      </div>
                      <p className="text-[11px] text-text-secondary mt-0.5">{mode.sublabel}</p>
                    </div>
                  </div>

                  {/* Filtered Area */}
                  <div
                    className="p-4 flex-1 space-y-4"
                    style={mode.filterId ? { filter: `url(#${mode.filterId})` } : undefined}
                  >
                    <SpecimenSuite />
                  </div>

                  {/* Summary Footer */}
                  <div className="px-3.5 py-2 bg-surface-raised/50 border-t border-surface-border text-[10px] text-text-secondary">
                    {mode.description}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-xl border border-surface-border bg-surface-card overflow-hidden shadow-sm">
              <div className="p-4 bg-surface-raised border-b border-surface-border flex items-center justify-between">
                <div>
                  <h2 className="text-base font-bold text-text">{activeCvd.label} Simulation</h2>
                  <p className="text-xs text-text-secondary mt-0.5">
                    {activeCvd.sublabel} · {activeCvd.description}
                  </p>
                </div>
                <span className="text-xs font-mono px-2 py-1 rounded bg-surface-bg border border-surface-border text-text">
                  Prevalence: {activeCvd.prevalence}
                </span>
              </div>

              <div
                className="p-6 space-y-6"
                style={activeCvd.filterId ? { filter: `url(#${activeCvd.filterId})` } : undefined}
              >
                <SpecimenSuite fullDetail />
              </div>
            </div>
          )}

          {/* Operational Dual-Coding Principles */}
          <div className="p-5 rounded-xl bg-surface-card border border-surface-border space-y-3">
            <h3 className="text-sm font-bold text-text flex items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-brand" />
              INDRA Dual-Coding & Redundancy Verification Checklist
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
              <div className="p-3 rounded-lg bg-surface-raised border border-surface-border space-y-1">
                <span className="font-semibold text-text">1. Shape & Iconography Redundancy</span>
                <p className="text-text-secondary text-[11px]">
                  Critical hazards utilize octagons/diamonds with double-stroke boundaries; High hazards utilize warning triangles; Verified reports display checkmark badges. No signal relies on color alone.
                </p>
              </div>
              <div className="div p-3 rounded-lg bg-surface-raised border border-surface-border space-y-1">
                <span className="font-semibold text-text">2. Saturated Severity vs Neutral Brand</span>
                <p className="text-text-secondary text-[11px]">
                  Saturated red and amber are legally quarantined for threat levels. Brand accents (terracotta, maritime teal, high-vis yellow, ivory) maintain $\ge 30^\circ$ hue separation or strict luminance differentiation.
                </p>
              </div>
              <div className="p-3 rounded-lg bg-surface-raised border border-surface-border space-y-1">
                <span className="font-semibold text-text">3. High Edge Contrast in Monochromacy</span>
                <p className="text-text-secondary text-[11px]">
                  Under 100% Achromatopsia, borders maintain $\ge 1.15:1$ (and $\ge 3:1$ in HUD) and text maintains $\ge 4.5:1$ against adjacent ground, ensuring zero information dropout in smoke or glare.
                </p>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

/**
 * Reusable Operational Specimen Suite
 * Contains Severity badges, status chips, hazard tags, buttons, and telemetry cards.
 */
function SpecimenSuite({ fullDetail = false }: { fullDetail?: boolean }) {
  return (
    <div className="space-y-4">
      {/* 1. Severity Scale */}
      <div>
        <span className="text-[10px] font-semibold tracking-wider uppercase text-text-secondary block mb-1.5">
          Operational Severity Scale (Dual-Coded)
        </span>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {/* Critical */}
          <div className="p-2 rounded-lg bg-severity-critical/10 border-2 border-severity-critical text-severity-critical flex items-center gap-1.5">
            <AlertOctagon className="w-4 h-4 shrink-0" />
            <div className="min-w-0">
              <span className="text-xs font-bold block truncate">CRITICAL</span>
              <span className="text-[9px] opacity-80 block truncate">Evacuate</span>
            </div>
          </div>

          {/* High */}
          <div className="p-2 rounded-lg bg-severity-high/10 border border-severity-high text-severity-high flex items-center gap-1.5">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            <div className="min-w-0">
              <span className="text-xs font-bold block truncate">HIGH</span>
              <span className="text-[9px] opacity-80 block truncate">Advisory</span>
            </div>
          </div>

          {/* Moderate */}
          <div className="p-2 rounded-lg bg-severity-moderate/10 border border-severity-moderate text-severity-moderate flex items-center gap-1.5">
            <Info className="w-4 h-4 shrink-0" />
            <div className="min-w-0">
              <span className="text-xs font-bold block truncate">MODERATE</span>
              <span className="text-[9px] opacity-80 block truncate">Watch</span>
            </div>
          </div>

          {/* Low */}
          <div className="p-2 rounded-lg bg-severity-low/10 border border-severity-low text-severity-low flex items-center gap-1.5">
            <CheckCircle2 className="w-4 h-4 shrink-0" />
            <div className="min-w-0">
              <span className="text-xs font-bold block truncate">LOW</span>
              <span className="text-[9px] opacity-80 block truncate">Normal</span>
            </div>
          </div>
        </div>
      </div>

      {/* 2. Verification Status */}
      <div>
        <span className="text-[10px] font-semibold tracking-wider uppercase text-text-secondary block mb-1.5">
          Verification Pipeline Status
        </span>
        <div className="flex flex-wrap gap-2">
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-status-verified/15 text-status-verified border border-status-verified/30">
            <ShieldCheck className="w-3.5 h-3.5" />
            Verified (Official)
          </span>
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-status-review/15 text-status-review border border-status-review/30">
            <Clock className="w-3.5 h-3.5" />
            Under Field Review
          </span>
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-status-auto/15 text-status-auto border border-status-auto/30">
            <Sparkles className="w-3.5 h-3.5" />
            Auto-Corroborated
          </span>
        </div>
      </div>

      {/* 3. Action Buttons & Brand Contrast */}
      <div>
        <span className="text-[10px] font-semibold tracking-wider uppercase text-text-secondary block mb-1.5">
          Interactive Hierarchy & CTAs
        </span>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="px-3 py-1.5 rounded-lg bg-brand text-brand-contrast text-xs font-bold shadow-sm hover:opacity-95 transition-opacity"
          >
            Dispatch Unit (Brand)
          </button>
          <button
            type="button"
            className="px-3 py-1.5 rounded-lg bg-surface-raised border border-surface-border text-text text-xs font-medium hover:bg-surface-raised/80 transition-colors"
          >
            Review EXIF Telemetry
          </button>
          <button
            type="button"
            className="px-3 py-1.5 rounded-lg bg-severity-critical text-brand-contrast text-xs font-bold hover:opacity-90 transition-opacity"
          >
            Trigger Siren
          </button>
        </div>
      </div>

      {/* 4. Categorical Hazard Badges (Option 1 Palette) */}
      <div>
        <span className="text-[10px] font-semibold tracking-wider uppercase text-text-secondary block mb-1.5">
          Categorical Hazards (Separated Hues)
        </span>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5">
          <div className="p-1.5 rounded bg-surface-raised border border-surface-border flex items-center gap-1.5 text-[11px]">
            <Wind className="w-3.5 h-3.5 text-hazard-cyclone" />
            <span className="font-medium text-text">Cyclone</span>
          </div>
          <div className="p-1.5 rounded bg-surface-raised border border-surface-border flex items-center gap-1.5 text-[11px]">
            <CloudRain className="w-3.5 h-3.5 text-hazard-flood" />
            <span className="font-medium text-text">Flood</span>
          </div>
          <div className="p-1.5 rounded bg-surface-raised border border-surface-border flex items-center gap-1.5 text-[11px]">
            <Sun className="w-3.5 h-3.5 text-hazard-heatwave" />
            <span className="font-medium text-text">Heatwave (Plum)</span>
          </div>
          <div className="p-1.5 rounded bg-surface-raised border border-surface-border flex items-center gap-1.5 text-[11px]">
            <Flame className="w-3.5 h-3.5 text-hazard-drought" />
            <span className="font-medium text-text">Drought</span>
          </div>
          <div className="p-1.5 rounded bg-surface-raised border border-surface-border flex items-center gap-1.5 text-[11px]">
            <Compass className="w-3.5 h-3.5 text-hazard-duststorm" />
            <span className="font-medium text-text">Dust Storm (Khaki)</span>
          </div>
          <div className="p-1.5 rounded bg-surface-raised border border-surface-border flex items-center gap-1.5 text-[11px]">
            <Layers className="w-3.5 h-3.5 text-hazard-landslide" />
            <span className="font-medium text-text">Landslide</span>
          </div>
        </div>
      </div>

      {/* 5. Live Incident Card Simulation */}
      {fullDetail && (
        <div className="p-4 rounded-xl bg-surface-raised border border-surface-border space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono text-text-secondary">EVENT ID: INC-2026-ODISHA-04</span>
            <span className="text-xs px-2 py-0.5 rounded font-bold bg-severity-critical/15 text-severity-critical border border-severity-critical/40">
              CAT-4 LANDFALL IMMINENT
            </span>
          </div>
          <h4 className="text-sm font-bold text-text">
            Severe Cyclonic Storm &apos;MAHASEN&apos; Coastal Inundation
          </h4>
          <p className="text-xs text-text-secondary">
            Estimated storm surge 3.8m above astronomical tide. Emergency evacuation corridors activated in Paradip and Kendrapara sectors.
          </p>
          <div className="flex items-center justify-between pt-2 border-t border-surface-border text-xs">
            <span className="text-text-secondary font-mono">Telemetry: 142 km/h · 968 hPa</span>
            <button
              type="button"
              className="flex items-center gap-1 px-3 py-1 rounded bg-brand text-brand-contrast text-xs font-semibold"
            >
              Dispatch Command <ArrowRight className="w-3 h-3" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

import type { Config } from 'tailwindcss';

function withOpacity(variableName: string) {
  return ({ opacityValue }: { opacityValue?: string }) => {
    if (opacityValue !== undefined) {
      return `rgb(var(${variableName}) / ${opacityValue})`;
    }
    return `rgb(var(${variableName}))`;
  };
}

const config: Config = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
    './src/lib/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        // ── Semantic Tokens ────────────────────────────────
        'surface-bg': withOpacity('--surface-bg'),
        surface: {
          DEFAULT: withOpacity('--surface'),
          raised: withOpacity('--surface-raised'),
          rail: withOpacity('--surface-rail'),
        },
        border: withOpacity('--border'),
        text: {
          DEFAULT: withOpacity('--text'),
          secondary: withOpacity('--text-secondary'),
          muted: withOpacity('--text-muted'),
          subtle: withOpacity('--text-subtle'),
        },
        brand: {
          DEFAULT: withOpacity('--brand'),
          contrast: withOpacity('--brand-contrast'),
          foreground: withOpacity('--brand-contrast'),
          soft: withOpacity('--brand-soft'),
        },
        'focus-ring': withOpacity('--focus-ring'),
        scrim: withOpacity('--scrim'),
        selection: withOpacity('--selection'),
        severity: {
          critical: withOpacity('--severity-critical'),
          'critical-soft': withOpacity('--severity-critical-soft'),
          high: withOpacity('--severity-high'),
          'high-soft': withOpacity('--severity-high-soft'),
          moderate: withOpacity('--severity-moderate'),
          'moderate-soft': withOpacity('--severity-moderate-soft'),
          low: withOpacity('--severity-low'),
          'low-soft': withOpacity('--severity-low-soft'),
        },
        status: {
          verified: withOpacity('--status-verified'),
          'verified-soft': withOpacity('--status-verified-soft'),
          pending: withOpacity('--status-pending'),
          'pending-soft': withOpacity('--status-pending-soft'),
          quarantined: withOpacity('--status-quarantined'),
          'quarantined-soft': withOpacity('--status-quarantined-soft'),
        },

        // ── Backward-Compatibility Aliases ────────────────
        paper: withOpacity('--surface-bg'),
        'paper-2': withOpacity('--surface-raised'),
        'paper-3': withOpacity('--border'),
        'card-bg': withOpacity('--surface'),
        ink: withOpacity('--text'),
        'ink-2': withOpacity('--text-secondary'),
        'ink-3': withOpacity('--text-muted'),
        'text-primary': withOpacity('--text'),
        'text-secondary': withOpacity('--text-secondary'),
        'text-muted': withOpacity('--text-muted'),

        // ── Sidebar Rail ──────────────────────────────────
        slate: {
          DEFAULT: '#26314A',
          '2': '#2E3D56',
          '3': '#374D6A',
          '50':  '#f8fafc',
          '100': '#f1f5f9',
          '200': '#e2e8f0',
          '300': '#cbd5e1',
          '400': '#94a3b8',
          '500': '#64748b',
          '600': '#475569',
          '700': '#334155',
          '800': '#1e293b',
          '850': '#162030',
          '900': '#0f172a',
          '950': '#020617',
        },

        terracotta: {
          DEFAULT: withOpacity('--brand'),
          hover: withOpacity('--brand'),
          light: withOpacity('--brand-soft'),
        },
        primary: {
          DEFAULT: withOpacity('--brand'),
          hover: withOpacity('--brand'),
          light: withOpacity('--brand-soft'),
          50:  '#FBF2EE',
          100: '#F5E8E7',
          500: '#C86040',
          600: '#B5482E',
          700: '#A03D25',
        },

        critical: {
          DEFAULT: withOpacity('--severity-critical'),
          light: withOpacity('--severity-critical-soft'),
          dark: withOpacity('--severity-critical'),
        },
        high: {
          DEFAULT: withOpacity('--severity-high'),
          light: withOpacity('--severity-high-soft'),
          dark: withOpacity('--severity-high'),
        },
        moderate: {
          DEFAULT: withOpacity('--severity-moderate'),
          light: withOpacity('--severity-moderate-soft'),
          dark: withOpacity('--severity-moderate'),
        },
        low: {
          DEFAULT: withOpacity('--severity-low'),
          light: withOpacity('--severity-low-soft'),
          dark: withOpacity('--severity-low'),
        },
        verified: {
          DEFAULT: withOpacity('--status-verified'),
          light: withOpacity('--status-verified-soft'),
          dark: withOpacity('--status-verified'),
        },
        review: {
          DEFAULT: withOpacity('--status-pending'),
          light: withOpacity('--status-pending-soft'),
        },
      },

      fontFamily: {
        sans:       ['var(--font-body)', 'Public Sans', 'system-ui', 'sans-serif'],
        display:    ['var(--font-display)', 'Fraunces', 'Georgia', 'serif'],
        instrument: ['var(--font-data)', 'JetBrains Mono', 'Cascadia Code', 'monospace'],
        mono:       ['var(--font-data)', 'JetBrains Mono', 'Cascadia Code', 'monospace'],
      },

      borderRadius: {
        'sm':  'var(--radius-sm, 4px)',
        DEFAULT: 'var(--radius-md, 6px)',
        'md':  'var(--radius-md, 6px)',
        'lg':  'var(--radius-lg, 8px)',
        'xl':  '10px',
        '2xl': '12px',
        '3xl': '16px',
      },

      boxShadow: {
        card:        'var(--shadow-1, 0 1px 3px rgba(30,42,59,0.06), 0 1px 2px rgba(30,42,59,0.04))',
        'card-hover':'var(--shadow-2, 0 4px 12px rgba(30,42,59,0.10), 0 2px 4px rgba(30,42,59,0.06))',
        'card-lg':   '0 8px 24px rgba(30,42,59,0.10), 0 4px 8px rgba(30,42,59,0.06)',
      },

      spacing: {
        '18': '4.5rem',
        '88': '22rem',
      },

      keyframes: {
        'pulse-ring': {
          '0%':   { transform: 'scale(0.8)', opacity: '1' },
          '100%': { transform: 'scale(2.2)', opacity: '0' },
        },
        shimmer: {
          '100%': { transform: 'translateX(100%)' },
        },
        'count-up': {
          '0%':   { opacity: '0', transform: 'translateY(10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'slide-in-top': {
          '0%':   { opacity: '0', transform: 'translateY(-10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'fade-in': {
          '0%':   { opacity: '0' },
          '100%': { opacity: '1' },
        },
        'pulse-dot': {
          '0%, 100%': { opacity: '1' },
          '50%':      { opacity: '0.4' },
        },
      },

      animation: {
        'pulse-ring':   'pulse-ring 1.5s cubic-bezier(0.215, 0.61, 0.355, 1) infinite',
        shimmer:        'shimmer 2s infinite',
        'slide-in-top': 'slide-in-top 0.3s ease-out',
        'fade-in':      'fade-in 0.5s ease-out',
        'pulse-dot':    'pulse-dot 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
    },
  },
  plugins: [],
};

export default config;

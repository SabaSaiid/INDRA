import type { Config } from 'tailwindcss';

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
        // ── Ground & Surface ──────────────────────────────
        paper:  '#F7F3EA',
        'paper-2': '#F0EBE0',
        'paper-3': '#E8E2D4',
        surface: '#F7F3EA',       // kept for compat
        'card-bg': '#FDFAF5',

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

        // ── Ink ───────────────────────────────────────────
        ink:   '#1E2A3B',
        'ink-2': '#4A5568',
        'ink-3': '#7A8599',
        'text-primary':   '#1E2A3B',
        'text-secondary': '#4A5568',
        'text-muted':     '#7A8599',

        // ── Accent ────────────────────────────────────────
        terracotta: {
          DEFAULT: '#B5482E',
          hover:   '#A03D25',
          light:   'rgba(181,72,46,0.12)',
        },
        primary: {
          DEFAULT: '#B5482E',
          hover:   '#A03D25',
          light:   '#F5E8E7',
          50:  '#FBF2EE',
          100: '#F5E8E7',
          500: '#C86040',
          600: '#B5482E',
          700: '#A03D25',
        },

        // ── Status — Low Pressure palette ─────────────────
        critical: {
          DEFAULT: '#8C2F26',
          light:   '#F5E8E7',
          dark:    '#6D1F18',
        },
        high: {
          DEFAULT: '#B8873A',
          light:   '#FBF2E4',
          dark:    '#9A6D28',
        },
        moderate: {
          DEFAULT: '#4A6670',
          light:   '#E6EFF1',
          dark:    '#374E57',
        },
        low: {
          DEFAULT: '#6B7280',
          light:   '#F3F4F6',
          dark:    '#4B5563',
        },
        verified: {
          DEFAULT: '#4C7A5B',
          light:   '#E7F2EC',
          dark:    '#3A5E46',
        },
        review: {
          DEFAULT: '#B8873A',
          light:   '#FBF2E4',
        },
      },

      fontFamily: {
        sans:       ['Public Sans', 'system-ui', 'sans-serif'],
        display:    ['Fraunces', 'Georgia', 'serif'],
        instrument: ['JetBrains Mono', 'Cascadia Code', 'monospace'],
        mono:       ['JetBrains Mono', 'Cascadia Code', 'monospace'],
      },

      borderRadius: {
        'sm':  '4px',
        DEFAULT: '6px',
        'md':  '8px',
        'lg':  '8px',
        'xl':  '10px',
        '2xl': '12px',
        '3xl': '16px',
      },

      boxShadow: {
        card:        '0 1px 3px rgba(30,42,59,0.06), 0 1px 2px rgba(30,42,59,0.04)',
        'card-hover':'0 4px 12px rgba(30,42,59,0.10), 0 2px 4px rgba(30,42,59,0.06)',
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

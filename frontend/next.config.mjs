import { PHASE_DEVELOPMENT_SERVER } from 'next/constants.js';

/** @type {import('next').NextConfig} */
const nextConfig = (phase) => {
  const isDev = phase === PHASE_DEVELOPMENT_SERVER;

  return {
    reactStrictMode: true,
    // NEXT_DIST_DIR overrides the output directory if set explicitly.
    // Otherwise:
    // - `next dev` builds into `.next-dev`
    // - `next build` builds into `.next` (or `.next-verify` for verification)
    // This strict isolation prevents `next build` or verification checks from wiping
    // the running dev server's chunk manifests and styles, which causes 404 CSS/JS errors.
    distDir: process.env.NEXT_DIST_DIR || (isDev ? '.next-dev' : '.next'),
    webpack: (config) => {
      // Use in-memory cache instead of filesystem packfile cache.
      // Filesystem packfiles fail on paths containing spaces ('0_Saba CSE', 'SIH 26'),
      // corrupting .next chunk manifests and triggering 'Cannot find module ./NNN.js'.
      // Memory cache completely eliminates disk corruption while preserving
      // seamless HMR chunk manifests and CSS extraction.
      config.cache = { type: 'memory' };
      return config;
    },
  };
};

export default nextConfig;

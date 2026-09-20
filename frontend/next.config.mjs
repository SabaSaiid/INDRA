/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
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

export default nextConfig;

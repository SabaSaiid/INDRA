/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  distDir: process.env.NEXT_DIST_DIR || '.next',
  webpack: (config) => {
    // Disable Webpack filesystem packfile cache in all modes.
    // PackFileCacheStrategy causes ENOENT and snapshot resolution failures on macOS,
    // which corrupts the chunk manifest and triggers 'Cannot find module ./NNN.js'.
    config.cache = false;
    return config;
  },
};

export default nextConfig;

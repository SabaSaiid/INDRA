/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  webpack: (config, { dev }) => {
    if (dev) {
      // Disable Webpack filesystem packfile cache in development mode.
      // Webpack's PackFileCacheStrategy causes ENOENT on rapid .pack.gz_ renames,
      // which corrupts the chunk manifest and triggers 'Cannot find module ./NNN.js' and unstyled 500 CSS/JS errors.
      config.cache = false;
    }
    return config;
  },
};

export default nextConfig;

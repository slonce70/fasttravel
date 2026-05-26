// @ts-check
import { initOpenNextCloudflareForDev } from '@opennextjs/cloudflare';

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The Cloudflare Workers runtime doesn't ship Sharp. Serve source images
  // directly for now; route through Cloudflare Images in a later phase.
  images: {
    unoptimized: true,
    remotePatterns: [
      { protocol: 'https', hostname: '**.tboholidays.com' },
      { protocol: 'https', hostname: '**.farvater.travel' },
      { protocol: 'https', hostname: 'images.unsplash.com' },
    ],
  },
};

export default nextConfig;

initOpenNextCloudflareForDev();

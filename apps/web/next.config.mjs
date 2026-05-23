// @ts-check

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Cloudflare Pages doesn't run Next.js' built-in image optimization loop
  // (Sharp). Set `unoptimized: true` and serve images directly; later we'll
  // route through Cloudflare Image Resizing (Phase 2).
  images: {
    unoptimized: true,
    remotePatterns: [
      { protocol: 'https', hostname: '**.tboholidays.com' },
      { protocol: 'https', hostname: '**.farvater.travel' },
      { protocol: 'https', hostname: 'images.unsplash.com' },
    ],
  },
  // We rely on the Cloudflare adapter to translate the build output. The
  // adapter runs `npx @cloudflare/next-on-pages` post-build (see scripts).
  // Edge-runtime is opted-in per route where needed.
};

export default nextConfig;

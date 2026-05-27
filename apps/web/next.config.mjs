// @ts-check
import { initOpenNextCloudflareForDev } from '@opennextjs/cloudflare';

// Audit quarter #18: the Next.js app on Cloudflare Workers had no
// `headers()` block. The API path goes through nginx which sets its own
// security headers, but anything the worker serves directly (HTML, RSC
// payloads, error pages) was unprotected. These are the standard
// "boring, do them everywhere" headers — no app-specific exceptions.
//
// CSP is intentionally minimal-but-real:
//   * default-src 'self' covers the catch-all
//   * 'unsafe-inline' on style-src is required by Tailwind's inlined
//     dynamic styles and Next.js' style tags; tightening this would
//     need nonce wiring through App Router which isn't worth the cost
//     for an MVP. Revisit when SSR streams stabilise.
//   * 'unsafe-eval' on script-src is required by Next dev-mode HMR;
//     prod builds don't need it but Cloudflare Workers eval some chunks.
//   * connect-src lists the live API + image CDN hostnames the app fetches.
//   * frame-ancestors 'none' replaces X-Frame-Options DENY (CSP3 spec).
const csp = [
  "default-src 'self'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "img-src 'self' data: https://*.tboholidays.com https://*.farvater.travel https://images.unsplash.com",
  "font-src 'self' data:",
  "style-src 'self' 'unsafe-inline'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
  "connect-src 'self' https://fasttravel.com.ua https://api.fasttravel.com.ua",
  "object-src 'none'",
  "upgrade-insecure-requests",
].join('; ');

const securityHeaders = [
  { key: 'Content-Security-Policy', value: csp },
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'X-Frame-Options', value: 'DENY' }, // legacy fallback for clients without CSP3
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  {
    // 2 years + subdomains + preload-eligible. Don't enable preload
    // until DNS for api.* and www.* is finalised — adding/removing a
    // host after preload submission requires a multi-month delisting.
    key: 'Strict-Transport-Security',
    value: 'max-age=63072000; includeSubDomains',
  },
  {
    // Lock down powerful browser APIs the app doesn't use. If a future
    // feature needs geolocation, add 'self' to that directive.
    key: 'Permissions-Policy',
    value: [
      'accelerometer=()',
      'autoplay=()',
      'camera=()',
      'display-capture=()',
      'fullscreen=(self)',
      'geolocation=()',
      'gyroscope=()',
      'microphone=()',
      'payment=()',
      'usb=()',
    ].join(', '),
  },
];

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
  async headers() {
    return [
      {
        // Apply to every route. Per-route overrides can be layered later
        // (e.g. tighter CSP on /api/* if Next handles any API itself).
        source: '/:path*',
        headers: securityHeaders,
      },
    ];
  },
};

export default nextConfig;

initOpenNextCloudflareForDev();

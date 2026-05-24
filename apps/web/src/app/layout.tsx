import type { Metadata, Viewport } from 'next';
import { Inter } from 'next/font/google';

import { Header } from '@/components/layout/Header';
import { Footer } from '@/components/layout/Footer';
import { QueryProvider } from '@/providers/query-provider';

import '@/styles/globals.css';

const inter = Inter({
  subsets: ['latin', 'cyrillic'],
  variable: '--font-inter',
  display: 'swap',
});

export const metadata: Metadata = {
  metadataBase: new URL('https://fasttravel.com.ua'),
  title: {
    default: 'FastTravel — календар цін на тури',
    template: '%s · FastTravel',
  },
  description:
    'Український агрегатор турів з календарем цін на десятки напрямків — Туреччина, Єгипет, ОАЕ, Греція, Україна та інші. Знаходимо аномальні знижки і постимо у Telegram.',
  openGraph: {
    type: 'website',
    locale: 'uk_UA',
    siteName: 'FastTravel',
    // Default share image. Per-route metadata can override (e.g. a
    // dynamic per-hotel image once we wire next/og on the API side).
    // 1200×630 is the canonical OG aspect; SVG renders crisply on
    // every preview crawler we care about (FB, Telegram, Twitter, LinkedIn).
    images: [
      {
        url: '/og-default.svg',
        width: 1200,
        height: 630,
        alt: 'FastTravel — календар цін на тури',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    images: ['/og-default.svg'],
  },
  robots: { index: true, follow: true },
};

export const viewport: Viewport = {
  themeColor: '#1e40af',
  width: 'device-width',
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="uk" className={inter.variable}>
      <body className="flex min-h-screen flex-col">
        <QueryProvider>
          <Header />
          <main className="flex-1">{children}</main>
          <Footer />
        </QueryProvider>
      </body>
    </html>
  );
}

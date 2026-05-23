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
    default: 'FastTravel — календар цін на тури в Туреччину',
    template: '%s · FastTravel',
  },
  description:
    'Український агрегатор турів з календарем цін. Знаходимо аномальні знижки на тури в Туреччину та постимо у Telegram.',
  openGraph: {
    type: 'website',
    locale: 'uk_UA',
    siteName: 'FastTravel',
  },
  twitter: { card: 'summary_large_image' },
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

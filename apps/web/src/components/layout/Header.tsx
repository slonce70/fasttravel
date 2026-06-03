import Link from 'next/link';
import { Container } from './Container';
import { DestinationsMenu } from './DestinationsMenu';
import { fetchDestinations } from '@/lib/api-client';
import { uniqueCountriesByIso } from '@/lib/countries';
import type { CountryOut } from '@/lib/types';

const STATIC_NAV = [
  { href: '/search', label: 'Пошук турів' },
  { href: '/deals', label: 'Гарячі знижки' },
  { href: '/cheap', label: 'Найдешевші' },
];

const TAIL_NAV = [
  { href: '/telegram', label: 'Telegram' },
  { href: '/about', label: 'Про нас' },
];

async function getTopCountries(): Promise<CountryOut[]> {
  try {
    const all = await fetchDestinations({ revalidate: 3600 });
    return uniqueCountriesByIso(all)
      .filter((c) => c.hotel_count > 0)
      .slice(0, 5);
  } catch {
    return [];
  }
}

export async function Header() {
  const topCountries = await getTopCountries();

  return (
    <header className="sticky top-0 z-30 border-b border-slate-200/80 bg-white/90 backdrop-blur supports-[backdrop-filter]:bg-white/75">
      <Container className="flex h-16 items-center justify-between gap-6">
        <Link href="/" className="flex items-center gap-2.5 font-semibold text-slate-950">
          <span
            aria-hidden
            className="grid h-8 w-8 place-items-center rounded-lg bg-teal-700 text-white shadow-sm"
          >
            <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4">
              <path
                d="M5 14.5 10.3 9l3.5 3.4L19 6.8"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path d="M5 18h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </span>
          <span className="text-base tracking-tight sm:text-lg">FastTravel</span>
          <span className="hidden text-xs font-normal text-slate-500 sm:inline">
            календар цін на тури
          </span>
        </Link>
        <nav aria-label="Головна навігація" className="hidden md:block">
          <ul className="flex items-center gap-1">
            {STATIC_NAV.map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className="rounded-md px-3 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-100 hover:text-teal-800"
                >
                  {item.label}
                </Link>
              </li>
            ))}
            {topCountries.length > 0 && <DestinationsMenu countries={topCountries} />}
            {TAIL_NAV.map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className="rounded-md px-3 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-100 hover:text-teal-800"
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        {/* Mobile: minimalist quick-links. Hamburger comes in Phase 2. */}
        <nav aria-label="Швидкі дії" className="flex items-center gap-1 md:hidden">
          <Link
            href="/search"
            className="rounded-md px-3 py-2 text-sm font-medium text-slate-700 hover:text-teal-800"
          >
            Пошук
          </Link>
          <Link href="/deals" className="rounded-md px-3 py-2 text-sm font-medium text-teal-700">
            Знижки
          </Link>
        </nav>
      </Container>
    </header>
  );
}

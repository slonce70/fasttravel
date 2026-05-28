import Link from 'next/link';
import { Container } from './Container';
import { fetchDestinations } from '@/lib/api-client';
import { uniqueCountriesByIso } from '@/lib/countries';
import type { CountryOut } from '@/lib/types';

const STATIC_NAV = [
  { href: '/search', label: 'Пошук турів' },
  { href: '/deals', label: 'Гарячі знижки' },
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
    <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/90 backdrop-blur supports-[backdrop-filter]:bg-white/70">
      <Container className="flex h-14 items-center justify-between gap-6">
        <Link href="/" className="flex items-center gap-2 font-semibold text-brand-800">
          <span aria-hidden className="text-xl">
            ✈️
          </span>
          <span className="text-base sm:text-lg">FastTravel</span>
          <span className="hidden text-xs font-normal text-slate-400 sm:inline">
            календар цін на тури
          </span>
        </Link>
        <nav aria-label="Головна навігація" className="hidden md:block">
          <ul className="flex items-center gap-1">
            {STATIC_NAV.map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className="rounded px-3 py-2 text-sm text-slate-700 transition-colors hover:bg-slate-100 hover:text-brand-800"
                >
                  {item.label}
                </Link>
              </li>
            ))}
            {topCountries.length > 0 && (
              <li className="group relative">
                {/* CSS-only dropdown — keeps Header a server component. The
                    trigger is a non-interactive visual hint; the actual menu
                    items are real <Link>s that focus-within keeps reachable
                    via keyboard tabbing. */}
                <span className="block cursor-default rounded px-3 py-2 text-sm text-slate-700 transition-colors group-hover:bg-slate-100 group-hover:text-brand-800">
                  Напрямки ▾
                </span>
                <div className="invisible absolute right-0 top-full z-40 mt-1 w-56 rounded-lg border border-slate-200 bg-white p-1 opacity-0 shadow-lg transition group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100">
                  {topCountries.map((c) => (
                    <Link
                      key={`${c.country_iso2}-${c.id}`}
                      href={`/destinations/${c.country_slug}`}
                      className="block rounded px-3 py-2 text-sm text-slate-700 hover:bg-slate-100 hover:text-brand-800"
                    >
                      {c.name_uk}
                      <span className="ml-2 text-xs text-slate-400">{c.hotel_count}</span>
                    </Link>
                  ))}
                </div>
              </li>
            )}
            {TAIL_NAV.map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className="rounded px-3 py-2 text-sm text-slate-700 transition-colors hover:bg-slate-100 hover:text-brand-800"
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        {/* Mobile: minimalist quick-links. Hamburger comes in Phase 2. */}
        <nav aria-label="Швидкі дії" className="md:hidden">
          <Link href="/deals" className="rounded px-3 py-2 text-sm font-medium text-accent-600">
            Знижки
          </Link>
        </nav>
      </Container>
    </header>
  );
}

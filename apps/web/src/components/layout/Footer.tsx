import Link from 'next/link';
import { Container } from './Container';
import { fetchDestinations } from '@/lib/api-client';
import { uniqueCountriesByIso } from '@/lib/countries';
import type { CountryOut } from '@/lib/types';

async function getTopCountries(): Promise<CountryOut[]> {
  try {
    const all = await fetchDestinations({ revalidate: 3600 });
    // API already sorts by hotel_count DESC — take first 6 with at least one
    // hotel. If the catalog is sparse this may yield fewer items; that's fine.
    return uniqueCountriesByIso(all)
      .filter((c) => c.hotel_count > 0)
      .slice(0, 6);
  } catch {
    return [];
  }
}

export async function Footer() {
  const topCountries = await getTopCountries();

  return (
    <footer className="mt-16 border-t border-slate-200 bg-white py-10 text-sm text-slate-500">
      <Container className="space-y-8">
        {topCountries.length > 0 && (
          <div>
            <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
              Популярні напрямки
            </h2>
            <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-2">
              {topCountries.map((c) => (
                <li key={`${c.country_iso2}-${c.id}`}>
                  <Link
                    href={`/destinations/${c.country_slug}`}
                    className="text-slate-700 hover:text-brand-800"
                  >
                    Тури в {c.name_uk}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="flex flex-col gap-4 border-t border-slate-100 pt-6 md:flex-row md:items-center md:justify-between">
          <p>
            © {new Date().getFullYear()} FastTravel — інформаційний агрегатор турів.
            <span className="ml-2 hidden text-xs sm:inline">Ми не туроператор.</span>
          </p>
          <nav aria-label="Допоміжна навігація">
            <ul className="flex flex-wrap gap-4">
              <li>
                <Link href="/about" className="hover:text-slate-700">
                  Про нас
                </Link>
              </li>
              <li>
                <Link href="/telegram" className="hover:text-slate-700">
                  Telegram-канал
                </Link>
              </li>
              <li>
                <a href="mailto:hello@fasttravel.com.ua" className="hover:text-slate-700">
                  hello@fasttravel.com.ua
                </a>
              </li>
            </ul>
          </nav>
        </div>
      </Container>
    </footer>
  );
}

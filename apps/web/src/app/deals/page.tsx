import type { Metadata } from 'next';
import Link from 'next/link';
import { Container } from '@/components/layout/Container';
import { DealsFeed } from './DealsFeed';
import { fetchDeals, fetchDestinations, userMessageForApiError } from '@/lib/api-client';
import { countriesForSelector } from '@/lib/countries';
import type { CountryOut } from '@/lib/types';

const DEALS_PAGE_SIZE = 18;

export const metadata: Metadata = {
  title: 'Гарячі знижки на тури',
  description:
    'Знижки на тури до Туреччини, Єгипту, ОАЕ, Греції та інших напрямків — аномально дешеві дати, спецціни операторів.',
};

// SSR з 5-хв ревалідацією — баланс свіжість/CDN-кеш.
export const revalidate = 300;

type DealsSearchParams = {
  country?: string;
  [key: string]: string | undefined;
};

export default async function DealsPage({
  searchParams,
}: {
  searchParams: Promise<DealsSearchParams>;
}) {
  const sp = await searchParams;
  const country = sp.country?.toUpperCase();
  let initial;
  let error: string | null = null;
  // Resolve the filtered country's display name the same way /search does:
  // look it up in the destinations list by ISO2. Best-effort — a failed lookup
  // just leaves the generic heading.
  let countryName: string | undefined;
  try {
    const [deals, countries] = await Promise.all([
      fetchDeals({ limit: DEALS_PAGE_SIZE, country }, { revalidate: 300 }),
      country ? getCountries() : Promise.resolve<CountryOut[]>([]),
    ]);
    initial = deals;
    countryName = country
      ? countries.find((c) => c.country_iso2.toUpperCase() === country)?.name_uk
      : undefined;
  } catch (e) {
    error = userMessageForApiError(e);
    initial = { items: [], total: 0, limit: DEALS_PAGE_SIZE, offset: 0 };
  }

  return (
    <Container className="space-y-6 py-8">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">
          {countryName ? `Гарячі знижки: ${countryName}` : 'Гарячі знижки'}
        </h1>
        {!error && (
          <p className="mt-1 text-sm text-slate-500">
            Усього виявлено {initial.total} {pluralDeals(initial.total)}.
          </p>
        )}
        {country && (
          <Link
            href="/deals"
            className="mt-1 inline-block text-sm font-medium text-brand-700 hover:text-brand-900"
          >
            Усі країни →
          </Link>
        )}
      </div>

      {error ? (
        <div className="rounded-xl bg-white p-10 text-center text-sm text-danger-600 ring-1 ring-slate-200">
          Не вдалося завантажити дані: {error}
        </div>
      ) : (
        <DealsFeed initial={initial} country={country} countryName={countryName} />
      )}
    </Container>
  );
}

async function getCountries(): Promise<CountryOut[]> {
  try {
    return countriesForSelector(await fetchDestinations({ revalidate: 3600 }));
  } catch {
    return countriesForSelector([]);
  }
}

function pluralDeals(n: number): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return 'знижку';
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return 'знижки';
  return 'знижок';
}

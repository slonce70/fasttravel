import type { Metadata } from 'next';
import Link from 'next/link';
import { Suspense } from 'react';
import { Container } from '@/components/layout/Container';
import { HotelCard } from '@/components/HotelCard';
import { SearchForm } from '@/components/SearchForm';
import { SearchSortControl } from '@/components/SearchSortControl';
import { TelegramCta } from '@/components/TelegramCta';
import { fetchDestinations, searchHotels, userMessageForApiError } from '@/lib/api-client';
import { accusativeCountry } from '@/lib/countries';
import {
  PAGE_SIZE,
  readParam,
  searchHref,
  toApiSearchParams,
  type RouteSearchParams,
} from '@/lib/search-params';
import type { CountryOut, SearchParams } from '@/lib/types';

export const metadata: Metadata = {
  title: 'Пошук турів',
  description: 'Підбір готелів за країною, датами, бюджетом і зірковістю.',
};

// Dynamic — query params drive the response, no caching that's worth the risk.
export const dynamic = 'force-dynamic';

async function getCountries(): Promise<CountryOut[]> {
  try {
    return await fetchDestinations({ revalidate: 3600 });
  } catch {
    return [];
  }
}

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<RouteSearchParams>;
}) {
  const sp = await searchParams;
  const params = toApiSearchParams(sp);

  const [countries, searchResult] = await Promise.all([
    getCountries(),
    (async () => {
      try {
        return { ok: true as const, value: await searchHotels(params) };
      } catch (e) {
        return {
          ok: false as const,
          error: userMessageForApiError(e),
        };
      }
    })(),
  ]);

  const results = searchResult.ok
    ? searchResult.value
    : {
        items: [],
        total: 0,
        limit: PAGE_SIZE,
        offset: 0,
        price_basis_adults: 2,
        price_basis_kids: [],
        pax_supported: true,
        pax_note: null,
      };
  const error = searchResult.ok ? null : searchResult.error;
  const from = results.total === 0 ? 0 : results.offset + 1;
  const to = Math.min(results.offset + results.items.length, results.total);
  const hasPaxNotice = searchResult.ok && !results.pax_supported;

  const selectedCountry = params.country
    ? countries.find((c) => c.country_iso2.toUpperCase() === params.country)
    : undefined;
  const heading = params.q
    ? `Готелі за назвою “${params.q}”`
    : selectedCountry
      ? `Тури в ${accusativeCountry(selectedCountry.name_uk)}`
      : 'Усі тури';

  return (
    <Container className="py-8">
      <div className="grid gap-6 lg:grid-cols-[300px_minmax(0,1fr)]">
        <aside className="lg:sticky lg:top-24 lg:self-start">
          <Suspense
            fallback={
              <div
                className="h-[520px] animate-pulse rounded-xl bg-slate-100 ring-1 ring-slate-200"
                aria-hidden
              />
            }
          >
            <SearchForm countries={countries} defaultCountry={params.country} variant="panel" />
          </Suspense>
        </aside>

        <div className="space-y-6">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-950">{heading}</h1>
            <p className="mt-1 text-sm text-slate-500">
              {error
                ? 'Не вдалося завантажити результати.'
                : `${results.total} ${plural(results.total)} знайдено${
                    results.items.length > 0 ? ` · показуємо ${from}-${to}` : ''
                  }`}
            </p>
          </div>

          {hasPaxNotice && (
            <div
              role="status"
              className="rounded-xl bg-amber-50 p-4 text-sm text-amber-900 ring-1 ring-amber-200"
            >
              Ціни у видачі зараз рахуються для {results.price_basis_adults} дорослих
              {results.price_basis_kids.length > 0
                ? ` і дітей ${results.price_basis_kids.join(', ')}`
                : ' без дітей'}
              . Обраний склад туристів збережено в пошуку, але live-ціна для нього буде уточнюватися
              на стороні оператора.
            </div>
          )}

          {!params.check_in && !readParam(sp, 'check_in') && !readParam(sp, 'check_in_min') && (
            <div className="rounded-xl bg-slate-50 p-4 text-sm text-slate-600 ring-1 ring-slate-200">
              Без дати заїзду показуємо найнижчу актуальну ціну, яку вже знайшов парсер. Для
              точнішого підбору оберіть дату, тривалість і харчування.
            </div>
          )}

          {error ? (
            <div className="rounded-xl bg-white p-10 text-center text-sm text-danger-600 ring-1 ring-slate-200">
              {error}
            </div>
          ) : results.items.length === 0 ? (
            <div className="rounded-xl bg-white p-10 text-center text-sm text-slate-500 ring-1 ring-slate-200">
              <p>
                Нічого не знайдено серед готелів з актуальними цінами. Спробуйте змінити дату,
                харчування, зірковість або країну.
              </p>
              <div className="mt-4 flex flex-wrap items-center justify-center gap-3">
                <Link
                  href="/search"
                  className="rounded-lg px-3 py-2 font-medium text-brand-700 ring-1 ring-slate-300 hover:bg-slate-50"
                >
                  Скинути фільтри
                </Link>
                {params.country && (
                  <Link
                    href={searchHref({ ...params, country: undefined }, 0)}
                    className="rounded-lg px-3 py-2 font-medium text-brand-700 ring-1 ring-slate-300 hover:bg-slate-50"
                  >
                    Шукати по всіх країнах
                  </Link>
                )}
              </div>
            </div>
          ) : (
            <>
              <div className="flex flex-col gap-3 rounded-xl bg-white p-3 ring-1 ring-slate-200 sm:flex-row sm:items-center sm:justify-between">
                <span className="text-sm font-medium text-slate-700">Варіанти</span>
                <SearchSortControl value={params.sort ?? 'price_asc'} />
              </div>
              <div className="grid gap-4">
                {results.items.map((h) => (
                  <HotelCard key={h.hotel_id} hotel={h} variant="row" />
                ))}
              </div>
              <SearchPagination params={params} results={results} />
              {/* Only show on non-empty results so a "0 готелів" search page
              doesn't get a CTA before the user has anything to act on. */}
              <TelegramCta />
            </>
          )}
        </div>
      </div>
    </Container>
  );
}

function SearchPagination({
  params,
  results,
}: {
  params: SearchParams;
  results: { total: number; limit: number; offset: number };
}) {
  if (results.total <= results.limit) return null;
  const currentPage = Math.floor(results.offset / results.limit) + 1;
  const pageCount = Math.ceil(results.total / results.limit);
  const prevOffset = Math.max(0, results.offset - results.limit);
  const nextOffset = results.offset + results.limit;
  const canPrev = results.offset > 0;
  const canNext = nextOffset < results.total;

  return (
    <nav
      aria-label="Сторінки результатів пошуку"
      className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-white p-3 text-sm ring-1 ring-slate-200"
    >
      <span className="text-slate-500">
        Сторінка {currentPage} з {pageCount}
      </span>
      <div className="flex items-center gap-2">
        {canPrev ? (
          <Link
            className="rounded-lg px-3 py-2 text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50"
            href={searchHref(params, prevOffset)}
          >
            Назад
          </Link>
        ) : (
          <span className="rounded-lg px-3 py-2 text-slate-300 ring-1 ring-slate-200">Назад</span>
        )}
        {canNext ? (
          <Link
            className="rounded-lg bg-brand-700 px-3 py-2 font-medium text-white hover:bg-brand-800"
            href={searchHref(params, nextOffset)}
          >
            Далі
          </Link>
        ) : (
          <span className="rounded-lg px-3 py-2 text-slate-300 ring-1 ring-slate-200">Далі</span>
        )}
      </div>
    </nav>
  );
}

function plural(n: number) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return 'готель';
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return 'готелі';
  return 'готелів';
}

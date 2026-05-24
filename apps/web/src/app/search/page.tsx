import type { Metadata } from 'next';
import Link from 'next/link';
import { Suspense } from 'react';
import { Container } from '@/components/layout/Container';
import { HotelCard } from '@/components/HotelCard';
import { SearchForm } from '@/components/SearchForm';
import { fetchDestinations, searchHotels } from '@/lib/api-client';
import type { CountryOut, SearchParams } from '@/lib/types';

export const metadata: Metadata = {
  title: 'Пошук турів',
  description: 'Підбір готелів за країною, датами, бюджетом і зірковістю.',
};

// Dynamic — query params drive the response, no caching that's worth the risk.
export const dynamic = 'force-dynamic';

type RouteSearchParams = {
  country?: string;
  // Phase 2 P0-1: backend now takes a single `check_in` (the day the user
  // wants to fly out) + `nights` + `meal_plan` rather than a date range.
  check_in?: string;
  nights?: string;
  meal_plan?: string;
  price_max?: string;
  stars_min?: string;
  // #28: pax composition. Backend ignores these for now (MV doesn't index by
  // pax); we pass them through so the future ittour adapter — which DOES
  // honour pax — gets them for free without another schema change.
  adults?: string;
  kids?: string; // comma-separated ages: "5,7,9"
  limit?: string;
  offset?: string;
  [key: string]: string | undefined;
};

const PAGE_SIZE = 24;

function readParam(sp: RouteSearchParams, key: string): string | undefined {
  return sp[key] ?? sp[`amp;${key}`];
}

function parseKids(raw: string | undefined): number[] | undefined {
  if (!raw) return undefined;
  const ages = raw
    .split(',')
    .map((s) => Number(s.trim()))
    .filter((n) => Number.isFinite(n) && n >= 1 && n <= 17);
  return ages.length > 0 ? ages : undefined;
}

function toApiParams(sp: RouteSearchParams): SearchParams {
  return {
    country: readParam(sp, 'country')?.toUpperCase(),
    check_in: readParam(sp, 'check_in') || undefined,
    nights: toNumber(readParam(sp, 'nights')),
    meal_plan: readParam(sp, 'meal_plan') || undefined,
    price_max: toNumber(readParam(sp, 'price_max')),
    stars_min: toNumber(readParam(sp, 'stars_min')),
    adults: toNumber(readParam(sp, 'adults')),
    kids: parseKids(readParam(sp, 'kids')),
    limit: toNumber(readParam(sp, 'limit')) ?? PAGE_SIZE,
    offset: toNumber(readParam(sp, 'offset')) ?? 0,
  };
}

function toNumber(raw: string | undefined): number | undefined {
  if (!raw) return undefined;
  const n = Number(raw);
  return Number.isFinite(n) ? n : undefined;
}

function accusativeCountry(name: string): string {
  // Same map as SearchForm — duplicated to keep both pure. Tiny enough that
  // moving to a shared lib would cost more than it's worth.
  const map: Record<string, string> = {
    Туреччина: 'Туреччину',
    Єгипет: 'Єгипет',
    'ОАЕ': 'ОАЕ',
    Греція: 'Грецію',
    Іспанія: 'Іспанію',
    Болгарія: 'Болгарію',
    Чорногорія: 'Чорногорію',
    Хорватія: 'Хорватію',
    Кіпр: 'Кіпр',
    Таїланд: 'Таїланд',
    Мальдіви: 'Мальдіви',
    Італія: 'Італію',
    Туніс: 'Туніс',
    'Домініканська Республіка': 'Домініканську Республіку',
    Україна: 'Україну',
  };
  return map[name] ?? name;
}

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
  const params = toApiParams(sp);

  const [countries, searchResult] = await Promise.all([
    getCountries(),
    (async () => {
      try {
        return { ok: true as const, value: await searchHotels(params) };
      } catch (e) {
        return {
          ok: false as const,
          error: e instanceof Error ? e.message : 'Невідома помилка',
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
  const heading = selectedCountry
    ? `Тури в ${accusativeCountry(selectedCountry.name_uk)}`
    : 'Усі тури';

  return (
    <Container className="space-y-6 py-8">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">{heading}</h1>
        <p className="mt-1 text-sm text-slate-500">
          {error
            ? 'Не вдалося завантажити результати.'
            : `${results.total} ${plural(results.total)} знайдено${
                results.total > 0 ? ` · показуємо ${from}-${to}` : ''
              }`}
        </p>
      </div>

      <Suspense fallback={<div className="h-44 rounded-2xl bg-white" />}>
        <SearchForm countries={countries} defaultCountry={params.country} />
      </Suspense>

      {hasPaxNotice && (
        <div
          role="status"
          className="rounded-xl bg-amber-50 p-4 text-sm text-amber-900 ring-1 ring-amber-200"
        >
          Ціни у видачі зараз рахуються для {results.price_basis_adults} дорослих
          {results.price_basis_kids.length > 0
            ? ` і дітей ${results.price_basis_kids.join(', ')}`
            : ' без дітей'}
          . Обраний склад туристів збережено в пошуку, але live-ціна для нього буде
          уточнюватися на стороні оператора.
        </div>
      )}

      {!params.check_in && !readParam(sp, 'check_in') && (
        <div className="rounded-xl bg-slate-50 p-4 text-sm text-slate-600 ring-1 ring-slate-200">
          Без дати заїзду показуємо найнижчу актуальну ціну, яку вже знайшов парсер.
          Для точнішого підбору оберіть дату, тривалість і харчування.
        </div>
      )}

      {error ? (
        <div className="rounded-xl bg-white p-10 text-center text-sm text-danger-600 ring-1 ring-slate-200">
          {error}
        </div>
      ) : results.items.length === 0 ? (
        <div className="rounded-xl bg-white p-10 text-center text-sm text-slate-500 ring-1 ring-slate-200">
          Нічого не знайдено серед готелів з актуальними цінами. Спробуйте змінити
          дату, харчування, зірковість або країну.
        </div>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {results.items.map((h) => (
              <HotelCard key={h.hotel_id} hotel={h} />
            ))}
          </div>
          <SearchPagination params={params} results={results} />
        </>
      )}
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
          <Link className="rounded-lg px-3 py-2 text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50" href={searchHref(params, prevOffset)}>
            Назад
          </Link>
        ) : (
          <span className="rounded-lg px-3 py-2 text-slate-300 ring-1 ring-slate-200">
            Назад
          </span>
        )}
        {canNext ? (
          <Link className="rounded-lg bg-brand-700 px-3 py-2 font-medium text-white hover:bg-brand-800" href={searchHref(params, nextOffset)}>
            Далі
          </Link>
        ) : (
          <span className="rounded-lg px-3 py-2 text-slate-300 ring-1 ring-slate-200">
            Далі
          </span>
        )}
      </div>
    </nav>
  );
}

function searchHref(params: SearchParams, offset: number): string {
  const qs = new URLSearchParams();
  if (params.country) qs.set('country', params.country);
  if (params.check_in) qs.set('check_in', params.check_in);
  if (params.nights) qs.set('nights', String(params.nights));
  if (params.meal_plan) qs.set('meal_plan', params.meal_plan);
  if (params.price_max) qs.set('price_max', String(params.price_max));
  if (params.stars_min) qs.set('stars_min', String(params.stars_min));
  if (params.adults) qs.set('adults', String(params.adults));
  if (params.kids && params.kids.length > 0) qs.set('kids', params.kids.join(','));
  qs.set('limit', String(params.limit ?? PAGE_SIZE));
  if (offset > 0) qs.set('offset', String(offset));
  return `/search?${qs.toString()}`;
}

function plural(n: number) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return 'готель';
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return 'готелі';
  return 'готелів';
}

import type { Metadata } from 'next';
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
  limit?: string;
  offset?: string;
};

function toApiParams(sp: RouteSearchParams): SearchParams {
  return {
    country: sp.country?.toUpperCase(),
    check_in: sp.check_in || undefined,
    nights: sp.nights ? Number(sp.nights) : undefined,
    meal_plan: sp.meal_plan || undefined,
    price_max: sp.price_max ? Number(sp.price_max) : undefined,
    stars_min: sp.stars_min ? Number(sp.stars_min) : undefined,
    limit: sp.limit ? Number(sp.limit) : 20,
    offset: sp.offset ? Number(sp.offset) : 0,
  };
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
    : { items: [], total: 0, limit: 20, offset: 0 };
  const error = searchResult.ok ? null : searchResult.error;

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
            : `${results.total} ${plural(results.total)} знайдено`}
        </p>
      </div>

      <Suspense fallback={<div className="h-44 rounded-2xl bg-white" />}>
        <SearchForm
          defaultExpanded
          countries={countries}
          defaultCountry={params.country}
        />
      </Suspense>

      {error ? (
        <div className="rounded-xl bg-white p-10 text-center text-sm text-danger-600 ring-1 ring-slate-200">
          {error}
        </div>
      ) : results.items.length === 0 ? (
        <div className="rounded-xl bg-white p-10 text-center text-sm text-slate-500 ring-1 ring-slate-200">
          Нічого не знайдено. Спробуйте змінити фільтри.
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {results.items.map((h) => (
            <HotelCard key={h.hotel_id} hotel={h} />
          ))}
        </div>
      )}
    </Container>
  );
}

function plural(n: number) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return 'готель';
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return 'готелі';
  return 'готелів';
}

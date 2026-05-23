import type { Metadata } from 'next';
import { Suspense } from 'react';
import { Container } from '@/components/layout/Container';
import { HotelCard } from '@/components/HotelCard';
import { SearchForm } from '@/components/SearchForm';
import { searchHotels } from '@/lib/api-client';
import type { SearchParams } from '@/lib/types';

export const metadata: Metadata = {
  title: 'Пошук турів',
  description: 'Підбір готелів за країною, датами, бюджетом і зірковістю.',
};

// Dynamic — query params drive the response, no caching that's worth the risk.
export const dynamic = 'force-dynamic';

type RouteSearchParams = {
  country?: string;
  check_in_min?: string;
  check_in_max?: string;
  price_max?: string;
  stars_min?: string;
  limit?: string;
  offset?: string;
};

function toApiParams(sp: RouteSearchParams): SearchParams {
  return {
    country: sp.country?.toUpperCase(),
    check_in_min: sp.check_in_min || undefined,
    check_in_max: sp.check_in_max || undefined,
    price_max: sp.price_max ? Number(sp.price_max) : undefined,
    stars_min: sp.stars_min ? Number(sp.stars_min) : undefined,
    limit: sp.limit ? Number(sp.limit) : 20,
    offset: sp.offset ? Number(sp.offset) : 0,
  };
}

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<RouteSearchParams>;
}) {
  const sp = await searchParams;
  const params = toApiParams(sp);

  let results;
  let error: string | null = null;
  try {
    results = await searchHotels(params);
  } catch (e) {
    error = e instanceof Error ? e.message : 'Невідома помилка';
    results = { items: [], total: 0, limit: 20, offset: 0 };
  }

  return (
    <Container className="space-y-6 py-8">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Пошук турів</h1>
        <p className="mt-1 text-sm text-slate-500">
          {error
            ? 'Не вдалося завантажити результати.'
            : `${results.total} ${plural(results.total)} знайдено`}
        </p>
      </div>

      <Suspense fallback={<div className="h-44 rounded-2xl bg-white" />}>
        <SearchForm defaultExpanded />
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

'use client';

import { useInfiniteQuery } from '@tanstack/react-query';
import { fetchDeals } from '@/lib/api-client';
import type { PaginatedDeals } from '@/lib/types';
import { DealCard } from '@/components/DealCard';
import { Button } from '@/components/ui/Button';

const PAGE_SIZE = 18;

export function DealsFeed({
  initial,
  country,
  countryName,
}: {
  initial: PaginatedDeals;
  country?: string;
  countryName?: string;
}) {
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage } = useInfiniteQuery({
    queryKey: ['deals', 'feed', country ?? null],
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      fetchDeals({ limit: PAGE_SIZE, offset: pageParam, country }, { signal }),
    getNextPageParam: (last, all) => {
      const loaded = all.reduce((sum, p) => sum + p.items.length, 0);
      return loaded < last.total ? loaded : undefined;
    },
    initialData: {
      pages: [initial],
      pageParams: [0],
    },
  });

  const items = data?.pages.flatMap((p) => p.items) ?? [];

  if (items.length === 0) {
    return (
      <div className="rounded-xl bg-white p-10 text-center text-sm text-slate-500 ring-1 ring-slate-200">
        {countryName
          ? `Поки немає виявлених знижок для напрямку «${countryName}».`
          : country
            ? 'Поки немає виявлених знижок для цього напрямку.'
            : 'Поки немає виявлених знижок.'}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 rounded-xl bg-white p-3 ring-1 ring-slate-200 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm font-medium text-slate-700">
          Показано {items.length} з {initial.total} {pluralDeals(initial.total)}
        </p>
        <p className="text-xs text-slate-500">
          Найсвіжіші цінові сигнали зверху, решту можна дозавантажити нижче.
        </p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((deal) => (
          <DealCard key={deal.id} deal={deal} />
        ))}
      </div>
      {hasNextPage && (
        <div className="flex justify-center">
          <Button
            variant="secondary"
            size="lg"
            onClick={() => fetchNextPage()}
            disabled={isFetchingNextPage}
          >
            {isFetchingNextPage ? 'Завантаження…' : 'Показати більше'}
          </Button>
        </div>
      )}
    </div>
  );
}

function pluralDeals(n: number): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return 'знижку';
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return 'знижки';
  return 'знижок';
}

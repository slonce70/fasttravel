'use client';

import { useInfiniteQuery } from '@tanstack/react-query';
import { fetchDeals } from '@/lib/api-client';
import type { PaginatedDeals } from '@/lib/types';
import { DealCard } from '@/components/DealCard';
import { Button } from '@/components/ui/Button';

const PAGE_SIZE = 50;

export function DealsFeed({ initial }: { initial: PaginatedDeals }) {
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage } = useInfiniteQuery({
    queryKey: ['deals', 'feed'],
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      fetchDeals({ limit: PAGE_SIZE, offset: pageParam }, { signal }),
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
        Поки немає виявлених знижок.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((deal) => (
          <DealCard key={deal.id} deal={deal} />
        ))}
      </div>
      {hasNextPage && (
        <div className="flex justify-center">
          <Button
            variant="secondary"
            size="md"
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

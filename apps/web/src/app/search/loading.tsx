import { Container } from '@/components/layout/Container';
import { Skeleton } from '@/components/ui/Skeleton';

/**
 * Route-level fallback for fresh navigations into /search (a force-dynamic
 * server round-trip). In-page submit/sort changes use useTransition instead
 * (SearchForm / SearchSortControl) to avoid remounting the form and losing
 * focus, so this only shows on a cold entry.
 *
 * Skeleton is decorative; the single wrapping region carries the one polite
 * announcement so a screen reader hears "Завантаження" once, not per tile.
 */
export default function SearchLoading() {
  return (
    <Container className="space-y-6 py-8">
      <div role="status" aria-live="polite" aria-label="Завантаження результатів пошуку">
        <div className="space-y-2">
          <Skeleton className="h-8 w-56" />
          <Skeleton className="h-4 w-40" />
        </div>
        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }, (_, i) => (
            <div
              key={i}
              className="flex h-full flex-col overflow-hidden rounded-2xl bg-white ring-1 ring-slate-200"
            >
              <Skeleton className="h-44 w-full rounded-none" />
              <div className="flex flex-1 flex-col gap-3 p-5">
                <Skeleton className="h-5 w-3/4" />
                <Skeleton className="h-4 w-1/2" />
                <Skeleton className="mt-auto h-6 w-1/3" />
              </div>
            </div>
          ))}
        </div>
      </div>
    </Container>
  );
}

'use client';

import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useTransition } from 'react';
import {
  DEFAULT_SEARCH_SORT,
  SEARCH_SORT_OPTIONS,
  normalizeSearchSort,
  type SearchSort,
} from '@/lib/search-sort';
import { serializeSearchParams, type SearchUrlValue } from '@/lib/search-params';

interface SearchSortControlProps {
  value: SearchSort;
}

export function SearchSortControl({ value }: SearchSortControlProps) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [isPending, startTransition] = useTransition();

  function handleChange(nextValue: SearchSort) {
    const values: Record<string, SearchUrlValue> = Object.fromEntries(params.entries());
    values.offset = undefined;
    values['amp;offset'] = undefined;
    values['amp;sort'] = undefined;
    values.sort = nextValue === DEFAULT_SEARCH_SORT ? undefined : nextValue;

    const qs = serializeSearchParams(values);
    const query = qs.toString();
    // useTransition keeps `isPending` true through the /search round-trip so
    // the control can disable itself during the in-page navigation. `push`
    // runs synchronously inside the callback.
    startTransition(() => {
      router.push(query ? `${pathname}?${query}` : pathname);
    });
  }

  return (
    <label className="flex items-center gap-2 text-sm text-slate-600">
      <span className="font-medium">Сортування</span>
      <select
        aria-label="Сортування результатів"
        value={normalizeSearchSort(value)}
        onChange={(event) => handleChange(normalizeSearchSort(event.target.value))}
        disabled={isPending}
        aria-busy={isPending}
        className="h-10 rounded-lg border border-slate-300 bg-white px-3 text-sm font-medium text-slate-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-brand-600 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {SEARCH_SORT_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

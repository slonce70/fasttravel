export const DEFAULT_SEARCH_SORT = 'price_asc';

export const SEARCH_SORT_OPTIONS = [
  { value: 'price_asc', label: 'Спочатку дешевші' },
  { value: 'price_desc', label: 'Спочатку дорожчі' },
  { value: 'rating_desc', label: 'Найвищий рейтинг' },
  { value: 'name_asc', label: 'Назва: А-Я' },
  { value: 'stars_desc', label: 'Більше зірок' },
] as const;

export type SearchSort = (typeof SEARCH_SORT_OPTIONS)[number]['value'];

const SEARCH_SORT_VALUES = new Set<string>(SEARCH_SORT_OPTIONS.map((option) => option.value));

export function normalizeSearchSort(raw: string | null | undefined): SearchSort {
  return raw && SEARCH_SORT_VALUES.has(raw) ? (raw as SearchSort) : DEFAULT_SEARCH_SORT;
}

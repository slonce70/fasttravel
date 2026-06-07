import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { PaginatedSearchResults } from '@/lib/types';

vi.mock('@/components/SearchForm', () => ({
  SearchForm: () => <div data-testid="search-form" />,
}));

vi.mock('@/components/SearchSortControl', () => ({
  SearchSortControl: () => <div data-testid="search-sort" />,
}));

vi.mock('@/components/HotelCard', () => ({
  HotelCard: () => <div data-testid="hotel-card" />,
}));

vi.mock('@/components/TelegramCta', () => ({
  TelegramCta: () => <div data-testid="telegram-cta" />,
}));

vi.mock('@/lib/api-client', () => ({
  fetchDestinations: vi.fn(),
  searchHotels: vi.fn(),
  userMessageForApiError: () => 'Не вдалося завантажити дані.',
}));

import { fetchDestinations, searchHotels } from '@/lib/api-client';
import SearchPage from './page';

const emptyResults: PaginatedSearchResults = {
  items: [],
  total: 0,
  limit: 24,
  offset: 0,
  price_basis_adults: 2,
  price_basis_kids: [],
  pax_supported: true,
  pax_note: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchDestinations).mockResolvedValue([]);
  vi.mocked(searchHotels).mockResolvedValue(emptyResults);
});

describe('SearchPage', () => {
  it('uses core country names for the heading when live destinations are empty', async () => {
    render(await SearchPage({ searchParams: Promise.resolve({ country: 'TR' }) }));

    expect(screen.getByRole('heading', { name: 'Тури в Туреччину' })).toBeInTheDocument();
  });
});

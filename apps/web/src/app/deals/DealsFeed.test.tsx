import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Deal, PaginatedDeals } from '@/lib/types';
import { DealsFeed } from './DealsFeed';

vi.mock('@/lib/api-client', () => ({
  fetchDeals: vi.fn(),
}));

vi.mock('@/components/DealCard', () => ({
  DealCard: ({ deal }: { deal: Deal }) => <article>{deal.hotel_name_uk}</article>,
}));

const deal: Deal = {
  id: 1,
  hotel_id: 42,
  operator_id: 1,
  check_in: '2026-06-14',
  nights: 7,
  meal_plan: 'AI',
  price_uah: 32200,
  baseline_p50: 51500,
  discount_pct: 37,
  deep_link: null,
  detected_at: '2026-05-26T08:00:00Z',
  posted_at: null,
  detection_method: 'calendar_anomaly',
  hotel_slug: 'belport-beach-hotel',
  hotel_name_uk: 'Belport Beach Hotel',
  hotel_stars: 4,
  hotel_photo_url: null,
  destination_name: 'Аланія',
};

function renderFeed(initial: PaginatedDeals) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DealsFeed initial={initial} />
    </QueryClientProvider>,
  );
}

describe('DealsFeed', () => {
  it('shows loaded progress and a strong load-more control', () => {
    renderFeed({
      items: [deal, { ...deal, id: 2, hotel_name_uk: 'Second Hotel' }],
      total: 20,
      limit: 18,
      offset: 0,
    });

    expect(screen.getByText('Показано 2 з 20 знижок')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Показати більше/i })).toHaveClass('h-12');
  });
});

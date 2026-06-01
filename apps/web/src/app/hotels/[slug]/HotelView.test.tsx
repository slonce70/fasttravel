// Behavior tests for the hotel-detail client wrapper. Two correctness-sensitive
// paths are locked here: (1) the on-mount auto-refresh fires at most once per
// 15-min sessionStorage cooldown and is fully disabled by the env flag — a
// regression re-fires a live farvater scrape on every page view ($0-budget
// cost); (2) CustomNightsInput clamps a commit to [1,30] and only calls back
// when the clamped value actually changed.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Hotel } from '@/lib/types';
import { triggerHotelRefresh } from '@/lib/api-client';
import { HotelView } from './HotelView';

vi.mock('@/lib/api-client', () => ({
  triggerHotelRefresh: vi.fn(),
}));

// The heavy data-fetching children are out of scope here — stub them so the
// test exercises HotelView's own refresh/clamp logic without their queries.
vi.mock('@/components/PriceCalendar', () => ({
  PriceCalendar: () => <div data-testid="price-calendar" />,
}));
vi.mock('@/components/OffersList', () => ({
  OffersList: () => <div data-testid="offers-list" />,
}));

const triggerRefreshMock = vi.mocked(triggerHotelRefresh);

const HOTEL: Hotel = {
  id: 99,
  canonical_slug: 'test-hotel',
  name_uk: 'Тестовий готель',
  name_en: 'Test Hotel',
  stars: 4,
  destination_id: 1,
  review_score: 8.5,
  review_count: 100,
  photos_jsonb: null,
  amenities: null,
  description_uk: null,
  last_updated: null,
  is_active: true,
};

function renderHotelView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <HotelView hotel={HOTEL} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  window.sessionStorage.clear();
  triggerRefreshMock.mockResolvedValue({ queued: false, reason: null });
  vi.stubEnv('NEXT_PUBLIC_DISABLE_HOTEL_REFRESH', '');
});

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllEnvs();
});

describe('HotelView auto-refresh cooldown', () => {
  it('fires an auto refresh on first mount', async () => {
    renderHotelView();

    // The mutation's mutationFn runs in a microtask after the on-mount effect.
    await waitFor(() => expect(triggerRefreshMock).toHaveBeenCalledTimes(1));
    // triggerHotelRefresh sees (id, { nights }) — `source` lives on the
    // mutation intent, not the api-client args. Auto path passes no nights.
    expect(triggerRefreshMock).toHaveBeenCalledWith(HOTEL.id, { nights: undefined });
  });

  it('does NOT re-fire on a second mount within the cooldown window', async () => {
    const first = renderHotelView();
    await waitFor(() => expect(triggerRefreshMock).toHaveBeenCalledTimes(1));
    first.unmount();

    // sessionStorage persists across mounts in jsdom → cooldown gate holds.
    renderHotelView();
    // Give any (incorrect) second refresh a chance to fire before asserting.
    await new Promise((r) => setTimeout(r, 50));
    expect(triggerRefreshMock).toHaveBeenCalledTimes(1);
  });

  it('never fires when the disable flag is set', async () => {
    vi.stubEnv('NEXT_PUBLIC_DISABLE_HOTEL_REFRESH', '1');

    renderHotelView();

    await new Promise((r) => setTimeout(r, 50));
    expect(triggerRefreshMock).toHaveBeenCalledTimes(0);
  });
});

describe('CustomNightsInput clamp', () => {
  it('clamps an over-range commit to 30 and calls the refresh once', async () => {
    // Disable the on-mount auto refresh so only the blur-commit reaches the mock.
    vi.stubEnv('NEXT_PUBLIC_DISABLE_HOTEL_REFRESH', '1');

    renderHotelView();
    expect(triggerRefreshMock).toHaveBeenCalledTimes(0);

    const input = screen.getByLabelText('Своя кількість ночей');
    // Number inputs are flaky under userEvent.type → drive change directly.
    fireEvent.change(input, { target: { value: '99' } });
    fireEvent.blur(input);

    expect(input).toHaveValue(30);
    await waitFor(() => expect(triggerRefreshMock).toHaveBeenCalledTimes(1));
    expect(triggerRefreshMock).toHaveBeenCalledWith(HOTEL.id, { nights: 30 });
  });

  it('reverts a non-numeric commit and does not refresh', async () => {
    vi.stubEnv('NEXT_PUBLIC_DISABLE_HOTEL_REFRESH', '1');

    renderHotelView();

    const input = screen.getByLabelText('Своя кількість ночей');
    fireEvent.change(input, { target: { value: 'abc' } });
    fireEvent.blur(input);

    // Reverts to the current value (7) and never commits.
    expect(input).toHaveValue(7);
    await new Promise((r) => setTimeout(r, 50));
    expect(triggerRefreshMock).toHaveBeenCalledTimes(0);
  });
});

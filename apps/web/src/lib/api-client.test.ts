import { afterEach, describe, expect, it, vi } from 'vitest';
import { fetchDealById, fetchDeals, userMessageForApiError } from './api-client';

const deal = {
  id: 42,
  hotel_id: 7,
  operator_id: 1,
  check_in: '2026-06-15',
  nights: 7,
  meal_plan: 'AI',
  price_uah: 8000,
  baseline_p50: 12000,
  discount_pct: 33,
  deep_link: 'https://farvater.travel/tour',
  detected_at: '2026-05-22T10:30:00Z',
  posted_at: null,
  hotel_slug: 'pegasos-resort-kemer',
  hotel_name_uk: 'Pegasos Resort',
  hotel_stars: 4,
  hotel_photo_url: 'https://cdn.example.test/hotel.jpg',
  destination_name: 'Анталія',
};

describe('fetchDealById', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('requests the canonical deal detail endpoint', async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => Response.json(deal));
    vi.stubGlobal('fetch', fetchMock);

    await expect(fetchDealById(42)).resolves.toMatchObject({ id: 42 });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url] = fetchMock.mock.calls[0]!;
    expect(url).toBe('http://localhost:8000/api/deals/42');
  });

  it('returns null for missing deals', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('not found', { status: 404 })),
    );

    await expect(fetchDealById(404)).resolves.toBeNull();
  });
});

describe('fetchDeals', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('passes country filters through to the backend', async () => {
    const fetchMock = vi.fn<typeof fetch>(async () =>
      Response.json({ items: [], total: 0, limit: 50, offset: 0 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await fetchDeals({ limit: 50, offset: 0, country: 'TR' });

    const [url] = fetchMock.mock.calls[0]!;
    expect(url).toBe('http://localhost:8000/api/deals?limit=50&offset=0&country=TR');
  });
});

describe('userMessageForApiError', () => {
  it('maps backend failures to user-safe Ukrainian copy', () => {
    const message = userMessageForApiError(new Error('API 500 on /api/search'));

    expect(message).toBe('Сервіс тимчасово недоступний. Спробуйте ще раз за хвилину.');
    expect(message).not.toContain('/api/search');
  });
});

import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  fetchCheapestTours,
  fetchDealById,
  fetchDeals,
  searchHotels,
  triggerHotelRefresh,
  userMessageForApiError,
} from './api-client';

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

describe('fetchCheapestTours', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('passes per_country and min_stars through to the backend', async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => Response.json([]));
    vi.stubGlobal('fetch', fetchMock);

    await fetchCheapestTours({ per_country: 3, min_stars: 3 });

    const [url] = fetchMock.mock.calls[0]!;
    expect(url).toBe('http://localhost:8000/api/cheapest-tours?per_country=3&min_stars=3');
  });

  it('omits the query string when no params are supplied', async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => Response.json([]));
    vi.stubGlobal('fetch', fetchMock);

    await fetchCheapestTours();

    const [url] = fetchMock.mock.calls[0]!;
    expect(url).toBe('http://localhost:8000/api/cheapest-tours');
  });
});

describe('userMessageForApiError', () => {
  it('maps backend failures to user-safe Ukrainian copy', () => {
    const message = userMessageForApiError(new Error('API 500 on /api/search'));

    expect(message).toBe('Сервіс тимчасово недоступний. Спробуйте ще раз за хвилину.');
    expect(message).not.toContain('/api/search');
  });
});

describe('triggerHotelRefresh', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('returns the parsed body on 200', async () => {
    const body = { queued: true, eta_seconds: 12 };
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Response.json(body)),
    );

    await expect(triggerHotelRefresh(7)).resolves.toEqual(body);
  });

  it('returns null on 404 and 500 (best-effort, never throws)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('not found', { status: 404 })),
    );
    await expect(triggerHotelRefresh(7)).resolves.toBeNull();

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('boom', { status: 500 })),
    );
    await expect(triggerHotelRefresh(7)).resolves.toBeNull();
  });

  it('returns null (does not throw) when fetch rejects', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('network down');
      }),
    );

    await expect(triggerHotelRefresh(7)).resolves.toBeNull();
  });

  it('appends ?nights= only when provided and POSTs', async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => Response.json({ queued: true }));
    vi.stubGlobal('fetch', fetchMock);

    await triggerHotelRefresh(7, { nights: 7 });

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe('http://localhost:8000/api/hotels/7/refresh?nights=7');
    expect(init?.method).toBe('POST');
  });

  it('omits the query string when nights is not supplied', async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => Response.json({ queued: true }));
    vi.stubGlobal('fetch', fetchMock);

    await triggerHotelRefresh(7);

    const [url] = fetchMock.mock.calls[0]!;
    expect(url).toBe('http://localhost:8000/api/hotels/7/refresh');
  });
});

describe('searchHotels array + empty serialization', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  function stubSearchFetch() {
    const fetchMock = vi.fn<typeof fetch>(async () =>
      Response.json({ items: [], total: 0, limit: 20, offset: 0 }),
    );
    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
  }

  it('serializes an array param as comma-joined values', async () => {
    const fetchMock = stubSearchFetch();

    await searchHotels({ kids: [5, 7, 9] });

    const [url] = fetchMock.mock.calls[0]!;
    // URLSearchParams percent-encodes the comma → %2C.
    expect(url).toContain('kids=5%2C7%2C9');
  });

  it('omits an empty array param', async () => {
    const fetchMock = stubSearchFetch();

    await searchHotels({ kids: [] });

    const [url] = fetchMock.mock.calls[0]!;
    expect(url).not.toContain('kids');
  });

  it('drops undefined / empty-string fields', async () => {
    const fetchMock = stubSearchFetch();

    await searchHotels({ country: undefined, meal_plan: '', stars_min: 4 });

    const [url] = fetchMock.mock.calls[0]!;
    expect(url).not.toContain('country');
    expect(url).not.toContain('meal_plan');
    expect(url).toContain('stars_min=4');
  });
});

// Route-level tests for the hotel detail page that the bot and deal cards
// link to. We exercise generateMetadata (canonical + not-found) and the
// page's slug-canonicalisation control flow, mocking the data fetch,
// next/navigation, and the heavy client children so the test stays focused
// on routing/metadata behaviour rather than calendar rendering.
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type * as ReactNS from 'react';
import type { Hotel } from '@/lib/types';

// React's `cache()` is request-scoped (Server Components); replace it with an
// identity wrapper so getHotel() just calls fetchHotel() in the test runtime.
vi.mock('react', async (importOriginal) => {
  const actual = await importOriginal<typeof ReactNS>();
  return { ...actual, cache: <T,>(fn: T): T => fn };
});

vi.mock('next/navigation', () => ({
  notFound: vi.fn(),
  permanentRedirect: vi.fn(),
}));

vi.mock('@/lib/api-client', () => ({ fetchHotel: vi.fn() }));

// Heavy / client-only children — out of scope for routing tests.
vi.mock('./HotelView', () => ({ HotelView: () => <div data-testid="hotel-view" /> }));
vi.mock('@/components/HotelPhotoCarousel', () => ({
  HotelPhotoCarousel: () => <div data-testid="carousel" />,
}));
vi.mock('@/components/TelegramCta', () => ({ TelegramCta: () => <div data-testid="tg-cta" /> }));

import { fetchHotel } from '@/lib/api-client';
import { notFound, permanentRedirect } from 'next/navigation';
import HotelPage, { generateMetadata } from './page';

const mockFetchHotel = vi.mocked(fetchHotel);

const HOTEL: Hotel = {
  id: 1,
  canonical_slug: 'belport-beach-hotel',
  name_uk: 'Belport Beach Hotel',
  name_en: 'Belport Beach',
  stars: 4,
  destination_id: 10,
  review_score: 8.6,
  review_count: 1240,
  photos_jsonb: null,
  amenities: ['Wi-Fi', 'Басейн'],
  description_uk: 'Готель біля моря з власним пляжем.',
  last_updated: '2026-05-20',
  is_active: true,
};

const params = (slug: string) => Promise.resolve({ slug });

beforeEach(() => {
  vi.clearAllMocks();
});

describe('hotels/[slug] generateMetadata', () => {
  it('sets canonical alternate + title for an existing hotel', async () => {
    mockFetchHotel.mockResolvedValue(HOTEL);

    const meta = await generateMetadata({ params: params('belport-beach-hotel') });

    expect(meta.title).toBe('Belport Beach Hotel — календар цін на тур');
    expect(meta.alternates?.canonical).toBe('/hotels/belport-beach-hotel');
  });

  it('returns not-found metadata for a missing hotel', async () => {
    mockFetchHotel.mockResolvedValue(null);

    const meta = await generateMetadata({ params: params('ghost-hotel') });

    expect(meta.title).toBe('Готель не знайдено');
    expect(meta.alternates).toBeUndefined();
  });
});

describe('hotels/[slug] HotelPage', () => {
  it('permanent-redirects a non-canonical slug to the canonical one', async () => {
    mockFetchHotel.mockResolvedValue(HOTEL);

    await HotelPage({ params: params('belport-old-slug') });

    expect(permanentRedirect).toHaveBeenCalledWith('/hotels/belport-beach-hotel');
    expect(notFound).not.toHaveBeenCalled();
  });

  it('renders the hotel name without redirecting on the canonical slug', async () => {
    mockFetchHotel.mockResolvedValue(HOTEL);

    render(await HotelPage({ params: params('belport-beach-hotel') }));

    expect(permanentRedirect).not.toHaveBeenCalled();
    expect(notFound).not.toHaveBeenCalled();
    expect(screen.getByText('Belport Beach Hotel')).toBeInTheDocument();
  });
});

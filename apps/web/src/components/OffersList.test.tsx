import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Offer } from '@/lib/types';
import { fetchOffers } from '@/lib/api-client';
import { OffersList, offerKey } from './OffersList';

vi.mock('@/lib/api-client', () => ({
  fetchOffers: vi.fn(),
}));

const fetchOffersMock = vi.mocked(fetchOffers);

function renderOffers(date: Date | null, rows?: Offer[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  if (rows) fetchOffersMock.mockResolvedValueOnce(rows);
  return render(
    <QueryClientProvider client={client}>
      <OffersList hotelId={42} date={date} nights={7} mealPlan="AI" />
    </QueryClientProvider>,
  );
}

const offer: Offer = {
  operator_id: 1,
  operator_code: 'farvater',
  check_in: '2026-07-01',
  nights: 7,
  meal_plan: 'AI',
  room_category: 'Standard',
  price_uah: 42000,
  price_original: 1000,
  currency: 'USD',
  deep_link: 'https://example.test/standard',
  observed_at: '2026-05-28T00:00:00Z',
};

describe('offerKey', () => {
  it('keeps room variants distinct for the same operator/date/meal', () => {
    const suite = {
      ...offer,
      room_category: 'Suite',
      price_uah: 51000,
      deep_link: 'https://example.test/suite',
    };

    expect(offerKey(offer)).not.toEqual(offerKey(suite));
  });
});

describe('OffersList render branches', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders the date-prompt and does NOT fetch when date is null', async () => {
    renderOffers(null);

    expect(screen.getByText(/Оберіть дату в календарі вище/)).toBeInTheDocument();
    // enabled: date != null → the query never runs.
    await waitFor(() => {
      expect(fetchOffersMock).toHaveBeenCalledTimes(0);
    });
  });

  it('renders offers cheapest-first with the badge only on min-price rows', async () => {
    const cheap: Offer = {
      ...offer,
      operator_code: 'cheapco',
      price_uah: 30000,
      deep_link: 'https://example.test/cheap',
    };
    const dear: Offer = {
      ...offer,
      operator_code: 'dearco',
      price_uah: 45000,
      deep_link: 'https://example.test/dear',
    };
    // Provide in reverse price order to prove client-side sorting.
    renderOffers(new Date('2026-07-01'), [dear, cheap]);

    await waitFor(() => expect(fetchOffersMock).toHaveBeenCalled());

    const items = await screen.findAllByRole('listitem');
    expect(items).toHaveLength(2);
    // Cheapest first. (The operator code is upper-cased via CSS only; the DOM
    // text node stays as the source value.)
    expect(within(items[0]!).getByText('cheapco')).toBeInTheDocument();
    expect(within(items[1]!).getByText('dearco')).toBeInTheDocument();
    // Badge only on the cheapest row.
    expect(within(items[0]!).getByText('Найнижча ціна')).toBeInTheDocument();
    expect(within(items[1]!).queryByText('Найнижча ціна')).toBeNull();
  });

  it('renders the affiliate buy link with the sponsorship rel + disclosure', async () => {
    renderOffers(new Date('2026-07-01'), [offer]);

    const link = await screen.findByRole('link', { name: /Купити/ });
    const rel = link.getAttribute('rel') ?? '';
    expect(rel).toContain('nofollow');
    expect(rel).toContain('sponsored');
    expect(link).toHaveAttribute('target', '_blank');
    expect(screen.getByText('Спонсорське посилання')).toBeInTheDocument();
  });

  it('announces the count in a polite live region with agreed grammar', async () => {
    renderOffers(new Date('2026-07-01'), [offer]);

    // 1 → singular "пропозиція" (uk pluralization), not the genitive "пропозицій".
    expect(await screen.findByText(/^\s*1\s+пропозиція\s*$/)).toBeInTheDocument();
  });

  it('renders the empty card when no offers match', async () => {
    renderOffers(new Date('2026-07-01'), []);

    expect(await screen.findByText(/пропозицій немає/)).toBeInTheDocument();
  });
});

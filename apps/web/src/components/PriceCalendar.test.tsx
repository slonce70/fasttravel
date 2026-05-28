import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { CalendarDay } from '@/lib/types';
import { fetchCalendar } from '@/lib/api-client';
import { PriceCalendar } from './PriceCalendar';

vi.mock('@/lib/api-client', () => ({
  fetchCalendar: vi.fn(),
}));

const fetchCalendarMock = vi.mocked(fetchCalendar);

function renderCalendar(rows: CalendarDay[]) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  fetchCalendarMock.mockResolvedValueOnce(rows);

  return render(
    <QueryClientProvider client={client}>
      <PriceCalendar hotelId={42} nights={7} mealPlan="AI" horizonDays={14} />
    </QueryClientProvider>,
  );
}

function day(check_in: string, price: number): CalendarDay {
  return {
    check_in,
    meal_plan: 'AI',
    min_price_uah: price,
    prices_by_night: { '7': price },
    observed_at: '2026-05-28T00:00:00Z',
  };
}

describe('PriceCalendar deal hints', () => {
  it('renders a backend-provided date-dip marker', async () => {
    renderCalendar([
      {
        ...day('2026-06-01', 100_000),
        date_dip_baseline_uah: 105_000,
        date_dip_discount_pct: 5,
        date_dip_sample_n: 7,
      },
      day('2026-06-02', 105_000),
      day('2026-06-03', 105_000),
      day('2026-06-04', 105_000),
      day('2026-06-05', 105_000),
      day('2026-06-06', 105_000),
      day('2026-06-07', 105_000),
      day('2026-06-08', 105_000),
    ]);

    await waitFor(() => expect(fetchCalendarMock).toHaveBeenCalled());

    expect(await screen.findByLabelText('цікава дата')).toBeInTheDocument();
  });

  it('does not infer a marker from aggregate calendar minima without backend annotation', async () => {
    renderCalendar([
      day('2026-06-01', 100_000),
      day('2026-06-02', 105_000),
      day('2026-06-03', 105_000),
      day('2026-06-04', 105_000),
      day('2026-06-05', 105_000),
      day('2026-06-06', 105_000),
      day('2026-06-07', 105_000),
      day('2026-06-08', 105_000),
    ]);

    await waitFor(() => expect(fetchCalendarMock).toHaveBeenCalled());

    expect(screen.queryByLabelText('цікава дата')).toBeNull();
  });

  it('describes calendar baselines as comparison hints, not old-price savings', async () => {
    renderCalendar([
      {
        ...day('2026-06-01', 100_000),
        date_dip_baseline_uah: 105_000,
        date_dip_discount_pct: 5,
        date_dip_sample_n: 7,
      },
      day('2026-06-02', 105_000),
      day('2026-06-03', 105_000),
      day('2026-06-04', 105_000),
      day('2026-06-05', 105_000),
      day('2026-06-06', 105_000),
      day('2026-06-07', 105_000),
      day('2026-06-08', 105_000),
    ]);

    const interestingDate = await screen.findByTitle(/нижче за орієнтир/i);

    expect(interestingDate).toHaveAttribute('title', expect.stringContaining('нижче за орієнтир'));
    expect(interestingDate).not.toHaveAttribute('title', expect.stringContaining('Знижка'));
    expect(interestingDate).not.toHaveAttribute('title', expect.stringContaining('звичайної'));
  });

  it('does not show a cross-nights fallback as an exact selected-night price', async () => {
    renderCalendar([
      {
        check_in: '2026-06-01',
        meal_plan: 'AI',
        min_price_uah: 90_000,
        prices_by_night: { '10': 90_000 },
        observed_at: '2026-05-28T00:00:00Z',
      },
    ]);

    await waitFor(() => expect(fetchCalendarMock).toHaveBeenCalled());

    expect(await screen.findByLabelText('1 червня 2026 р.: цін немає')).toBeInTheDocument();
    expect(screen.queryByLabelText(/1 червня 2026.*від 90/i)).toBeNull();
  });
});

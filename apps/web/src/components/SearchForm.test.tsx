import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { localTodayIso } from '@/lib/search-params';
import type { CountryOut } from '@/lib/types';
import { SearchForm } from './SearchForm';

const push = vi.fn();
const currentParams = new URLSearchParams();

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => currentParams,
}));

const countries: CountryOut[] = [
  {
    id: 1,
    country_iso2: 'TR',
    country_slug: 'turkey',
    name_uk: 'Туреччина',
    name_en: 'Turkey',
    hotel_count: 12,
    regions: [],
  },
  {
    id: 2,
    country_iso2: 'EG',
    country_slug: 'egypt',
    name_uk: 'Єгипет',
    name_en: 'Egypt',
    hotel_count: 8,
    regions: [],
  },
];

describe('SearchForm', () => {
  beforeEach(() => {
    push.mockClear();
    for (const key of Array.from(currentParams.keys())) currentParams.delete(key);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('drops API-invalid URL filter defaults before rendering the form', async () => {
    currentParams.set('check_in', 'tomorrow');
    currentParams.set('nights', '7.5');
    currentParams.set('price_max', '-5');
    currentParams.set('stars_min', '9');

    render(<SearchForm countries={countries} />);

    expect(screen.getByLabelText('Дата заїзду')).toHaveValue('');
    expect(screen.getByLabelText('Кількість ночей')).toHaveValue('');
    expect(screen.getByLabelText('Бюджет, ₴')).toHaveValue(null);
    expect(screen.getByLabelText('Зірок, не менше')).toHaveValue('');
  });

  it('submits only API-safe query params for filter controls', async () => {
    const user = userEvent.setup();
    render(<SearchForm countries={countries} />);

    await user.type(screen.getByLabelText('Назва готелю'), 'Rixos Premium');
    await user.selectOptions(screen.getByLabelText('Країна призначення'), 'TR');
    await user.selectOptions(screen.getByLabelText('Кількість ночей'), '7');
    await user.selectOptions(screen.getByLabelText('Зірок, не менше'), '5');
    await user.click(screen.getByRole('button', { name: /знайти тури/i }));

    expect(push).toHaveBeenCalledWith(
      '/search?country=TR&nights=7&stars_min=5&q=Rixos+Premium&adults=2',
    );
  });

  it('can render the Travel + Data hero variant with cheap-date CTA copy', () => {
    render(<SearchForm countries={countries} variant="hero" />);

    expect(screen.getByRole('button', { name: /знайти дешеві дати/i })).toBeInTheDocument();
    expect(screen.getByText(/точний календар/i)).toBeInTheDocument();
  });

  it('can render a vertical panel variant for the data-console search page', () => {
    render(<SearchForm countries={countries} variant="panel" />);

    expect(screen.getByRole('button', { name: /знайти тури/i })).toBeInTheDocument();
    expect(screen.getByText(/Параметри пошуку/i)).toBeInTheDocument();
    expect(screen.getByLabelText('Назва готелю')).toBeInTheDocument();
  });

  it('updates selected country value and submit copy after choosing a country', async () => {
    const user = userEvent.setup();
    render(<SearchForm countries={countries} />);

    await user.selectOptions(screen.getByLabelText('Країна призначення'), 'TR');

    expect(screen.getByLabelText('Країна призначення')).toHaveValue('TR');
    expect(screen.getByRole('button', { name: 'Знайти тури в Туреччину' })).toBeInTheDocument();
  });

  it('prefills country from defaultCountry when URL has no country', async () => {
    const user = userEvent.setup();
    render(<SearchForm countries={countries} defaultCountry="EG" />);

    expect(screen.getByLabelText('Країна призначення')).toHaveValue('EG');

    await user.click(screen.getByRole('button', { name: 'Знайти тури в Єгипет' }));

    expect(push).toHaveBeenCalledWith('/search?country=EG&adults=2');
  });

  it('constrains the check-in input to today and later', () => {
    const localMidnightBoundary = new Date(2026, 0, 10, 0, 30, 0);
    vi.useFakeTimers();
    vi.setSystemTime(localMidnightBoundary);

    render(<SearchForm countries={countries} />);

    expect(localMidnightBoundary.toISOString().slice(0, 10)).toBe('2026-01-09');
    expect(screen.getByLabelText('Дата заїзду')).toHaveAttribute('min', localTodayIso());
  });

  it('navigates through a transition so the submit URL is still pushed once', async () => {
    const user = userEvent.setup();
    render(<SearchForm countries={countries} />);

    await user.selectOptions(screen.getByLabelText('Країна призначення'), 'TR');
    await user.click(screen.getByRole('button', { name: /знайти тури/i }));

    expect(push).toHaveBeenCalledTimes(1);
    expect(push).toHaveBeenCalledWith('/search?country=TR&adults=2');
  });

  it('keeps core countries selectable when the live destinations catalog is empty', async () => {
    const user = userEvent.setup();
    render(<SearchForm countries={[]} />);

    await user.selectOptions(screen.getByLabelText('Країна призначення'), 'TR');
    await user.click(screen.getByRole('button', { name: /знайти тури/i }));

    expect(screen.getByRole('option', { name: 'Туреччина' })).toBeInTheDocument();
    expect(push).toHaveBeenCalledWith('/search?country=TR&adults=2');
  });

  it('syncs controlled fields when URL filters change after mount', async () => {
    const user = userEvent.setup();
    currentParams.set('country', 'TR');
    const { rerender } = render(<SearchForm countries={countries} />);

    expect(screen.getByLabelText('Країна призначення')).toHaveValue('TR');

    currentParams.delete('country');
    rerender(<SearchForm countries={countries} />);

    expect(screen.getByLabelText('Країна призначення')).toHaveValue('');
    await user.click(screen.getByRole('button', { name: /знайти тури/i }));

    expect(push).toHaveBeenCalledWith('/search?adults=2');
  });

  it('injects a synthetic option so an out-of-range nights filter stays visible', () => {
    currentParams.set('nights', '3');

    render(<SearchForm countries={countries} />);

    // The controlled select holds the URL value and now has a matching option,
    // so it is not silently reset to "Будь-яка".
    expect(screen.getByLabelText('Кількість ночей')).toHaveValue('3');
    const options = screen.getByLabelText('Кількість ночей').querySelectorAll('option');
    expect(Array.from(options).map((o) => o.value)).toContain('3');
  });
});

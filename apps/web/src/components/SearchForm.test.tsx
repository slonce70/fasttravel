import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
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
];

describe('SearchForm', () => {
  beforeEach(() => {
    push.mockClear();
    for (const key of Array.from(currentParams.keys())) currentParams.delete(key);
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

    await user.selectOptions(screen.getByLabelText('Країна призначення'), 'TR');
    await user.selectOptions(screen.getByLabelText('Кількість ночей'), '7');
    await user.selectOptions(screen.getByLabelText('Зірок, не менше'), '5');
    await user.click(screen.getByRole('button', { name: /знайти тури/i }));

    expect(push).toHaveBeenCalledWith('/search?country=TR&nights=7&stars_min=5&adults=2');
  });
});

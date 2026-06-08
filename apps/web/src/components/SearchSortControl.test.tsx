import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SearchSortControl } from './SearchSortControl';

const push = vi.fn();
let currentParams = new URLSearchParams();

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
  usePathname: () => '/search',
  useSearchParams: () => currentParams,
}));

describe('SearchSortControl', () => {
  beforeEach(() => {
    push.mockClear();
    currentParams = new URLSearchParams();
  });

  it('pushes the chosen non-default sort and drops any stale offset', async () => {
    const user = userEvent.setup();
    currentParams = new URLSearchParams('country=TR&offset=24');
    render(<SearchSortControl value="price_asc" />);

    await user.selectOptions(screen.getByLabelText('Сортування результатів'), 'price_desc');

    expect(push).toHaveBeenCalledTimes(1);
    expect(push).toHaveBeenCalledWith('/search?country=TR&sort=price_desc');
  });

  it('clears the sort param when the default is selected so the URL stays canonical', async () => {
    const user = userEvent.setup();
    currentParams = new URLSearchParams('country=TR&sort=price_desc');
    render(<SearchSortControl value="price_desc" />);

    await user.selectOptions(screen.getByLabelText('Сортування результатів'), 'price_asc');

    expect(push).toHaveBeenCalledWith('/search?country=TR');
  });

  it('removes pre-existing escaped amp;offset / amp;sort and empty keys on sort change', async () => {
    const user = userEvent.setup();
    currentParams = new URLSearchParams('country=TR&meal_plan=&amp;offset=48&amp;sort=name_asc');
    render(<SearchSortControl value="price_asc" />);

    await user.selectOptions(screen.getByLabelText('Сортування результатів'), 'price_desc');

    const pushedUrl = push.mock.calls[0]?.[0] as string;
    expect(pushedUrl).toBe('/search?country=TR&sort=price_desc');
    expect(pushedUrl).toContain('sort=price_desc');
    expect(pushedUrl).not.toContain('offset');
    expect(pushedUrl).not.toContain('meal_plan');
    expect(pushedUrl).not.toContain('amp%3Boffset');
    expect(pushedUrl).not.toContain('amp%3Bsort');
    expect(pushedUrl).not.toContain('amp;offset');
    expect(pushedUrl).not.toContain('amp;sort');
  });
});

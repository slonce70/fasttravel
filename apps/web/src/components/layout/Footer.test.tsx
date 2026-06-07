import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Footer, copyrightYear } from './Footer';

vi.mock('@/lib/api-client', () => ({
  fetchDestinations: vi.fn(async () => []),
}));

describe('Footer', () => {
  it('derives the copyright year from the supplied date', () => {
    expect(copyrightYear(new Date('2027-01-01T00:00:00Z'))).toBe(2027);
  });

  it('keeps the legal disclaimer readable in accessible text', async () => {
    render(await Footer());

    expect(
      screen.getByText((_content, element) =>
        Boolean(
          element?.tagName === 'P' &&
            element.textContent?.includes(
              'FastTravel — інформаційний агрегатор турів. Ми не туроператор.',
            ),
        ),
      ),
    ).toBeInTheDocument();
  });
});

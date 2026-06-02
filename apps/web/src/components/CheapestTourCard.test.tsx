// Component-shape test for CheapestTourCard. The load-bearing contract is
// HONESTY: «ціна від» price, link to the hotel page, and the absence of any
// discount cue («знижка» / «−X%» / strike-through) — this card is NOT a deal.
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { CheapestTour } from '@/lib/types';
import { CheapestTourCard } from './CheapestTourCard';

vi.mock('next/link', () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const ws = (s: string) => s.replace(/\s/g, ' ');

const baseTour: CheapestTour = {
  country_iso2: 'BG',
  country_name: 'Болгарія',
  hotel_id: 46481,
  hotel_slug: 'fv-bg-chuchulev',
  hotel_name: 'Chuchulev Hotel',
  stars: 3,
  review_score: 9.2,
  review_count: 4,
  check_in: '2026-06-06',
  nights: 7,
  meal_plan: 'RO',
  price_uah: 18210,
  deep_link: 'https://farvater.travel/uk/hotel/bg/chuchulev?q=x',
  rank: 1,
};

describe('CheapestTourCard', () => {
  it('renders the hotel name, slug link and «ціна від» price', () => {
    const { container } = render(<CheapestTourCard tour={baseTour} />);
    expect(screen.getByText('Chuchulev Hotel')).toBeInTheDocument();
    expect(screen.getByRole('link')).toHaveAttribute('href', '/hotels/fv-bg-chuchulev');
    expect(screen.getByText('ціна від')).toBeInTheDocument();
    expect(ws(container.textContent ?? '')).toContain('18 210 ₴');
  });

  it('labels the link with the hotel name and «ціна від» price for a11y', () => {
    render(<CheapestTourCard tour={baseTour} />);
    const label = screen.getByRole('link').getAttribute('aria-label') ?? '';
    expect(label).toContain('Chuchulev Hotel');
    expect(ws(label)).toContain('ціна від 18 210 ₴');
  });

  it('shows the review score and check-in / nights / meal plan', () => {
    render(<CheapestTourCard tour={baseTour} />);
    expect(screen.getByText('9.2')).toBeInTheDocument();
    expect(screen.getByText(/без харчування/i)).toBeInTheDocument();
    expect(screen.getByText(/заїзд/)).toBeInTheDocument();
  });

  it('NEVER renders a discount cue (no «знижка», no «−%», no strike-through)', () => {
    const { container } = render(<CheapestTourCard tour={baseTour} />);
    const text = container.textContent ?? '';
    expect(text).not.toMatch(/знижк/i);
    expect(text).not.toMatch(/[-−]\s*\d+\s*%/);
    expect(container.querySelector('.line-through')).toBeNull();
  });

  it('omits the review line when review_score is null', () => {
    render(<CheapestTourCard tour={{ ...baseTour, review_score: null }} />);
    expect(screen.queryByText(/за \d+ відгуками/)).toBeNull();
  });
});

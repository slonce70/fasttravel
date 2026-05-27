// Component-shape tests for DealCard.
//
// These don't try to assert exact pixel layout — that's brittle and
// tailwind classes already encode it. We assert the things the
// frontend contract promises:
//   * the hotel name renders and links to /hotels/{slug}
//   * the discount badge shows the rounded % + fire emoji
//   * the strike-through baseline price is rendered when baseline > price
//   * the affiliate CTA appears only when deep_link exists and carries
//     rel="sponsored" (Ukrainian advertising-law requirement, audit hint)
//   * the savings layout doesn't crash on missing optional fields
//     (no destination, no photo, no deep_link)
//
// We mock next/link because the real Link expects RouterContext.

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Deal } from '@/lib/types';
import { DealCard } from './DealCard';

// Lightweight next/link stub — renders an <a> so RTL can query by role.
type LinkProps = React.AnchorHTMLAttributes<HTMLAnchorElement> & {
  href: string | { pathname?: string };
  children?: React.ReactNode;
};
vi.mock('next/link', () => ({
  default: ({ href, children, ...props }: LinkProps) => (
    <a href={typeof href === 'string' ? href : '#'} {...props}>
      {children}
    </a>
  ),
}));

const fullDeal: Deal = {
  id: 1,
  hotel_id: 42,
  operator_id: 1,
  check_in: '2026-06-14',
  nights: 7,
  meal_plan: 'AI',
  price_uah: 32200,
  baseline_p50: 51500,
  discount_pct: 37.4,
  deep_link: 'https://farvater.travel/uk/hotel/tr/belport?q=tour-123',
  detected_at: '2026-05-26T08:00:00Z',
  posted_at: null,
  detection_method: 'calendar_anomaly',
  hotel_slug: 'belport-beach-hotel',
  hotel_name_uk: 'Belport Beach Hotel',
  hotel_stars: 4,
  hotel_photo_url: 'https://images.unsplash.com/photo.jpg',
  destination_name: 'Аланія',
};

describe('DealCard', () => {
  it('shows hotel name + slug-based detail link', () => {
    render(<DealCard deal={fullDeal} />);
    const heading = screen.getByText('Belport Beach Hotel');
    expect(heading).toBeInTheDocument();
    // Permalink anchor under the card footer
    expect(screen.getByLabelText(/Постійне посилання/i)).toHaveAttribute(
      'href',
      '/deals/1',
    );
  });

  it('rounds the discount percent and includes the fire emoji', () => {
    render(<DealCard deal={fullDeal} />);
    // 37.4 → -37
    expect(screen.getByText(/-37%/)).toBeInTheDocument();
    expect(screen.getByText(/🔥/)).toBeInTheDocument();
  });

  it('renders strike-through baseline price when baseline > price', () => {
    render(<DealCard deal={fullDeal} />);
    // "зазвичай 51 500 ₴" — non-breaking space inside the formatter,
    // so use a relaxed regex (only on prefix + the integer part).
    expect(screen.getByText(/зазвичай/i)).toBeInTheDocument();
    expect(screen.getByText(/51/)).toBeInTheDocument();
    // Current price uses bigger font but same component — verify present.
    expect(screen.getByText(/32/)).toBeInTheDocument();
  });

  it('renders the affiliate CTA with rel="sponsored noopener nofollow"', () => {
    render(<DealCard deal={fullDeal} />);
    const cta = screen.getByRole('link', { name: /Купити тур/i });
    expect(cta).toHaveAttribute('href', fullDeal.deep_link!);
    expect(cta.getAttribute('rel')).toContain('sponsored');
    expect(cta.getAttribute('rel')).toContain('nofollow');
    expect(cta.getAttribute('rel')).toContain('noopener');
    // Visible "Спонсорське посилання" disclosure (Ukr ad law).
    expect(screen.getByText(/Спонсорське посилання/i)).toBeInTheDocument();
  });

  it('renders without crashing when optional fields are missing', () => {
    const minimal: Deal = {
      ...fullDeal,
      destination_name: null,
      hotel_stars: null,
      hotel_photo_url: null,
      deep_link: null,
    };
    render(<DealCard deal={minimal} />);
    expect(screen.getByText('Belport Beach Hotel')).toBeInTheDocument();
    // No CTA when deep_link is null.
    expect(screen.queryByRole('link', { name: /Купити/i })).toBeNull();
  });
});

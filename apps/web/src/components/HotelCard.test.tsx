// Component-shape tests for HotelCard (search/destination grids). Asserts the
// contract: name + slug link + "від" price, and the two honesty cues —
// duration-fallback badge and the ≥6h price-age note — plus the no-photo
// placeholder. Layout/tailwind is intentionally not asserted.
import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { SearchResultItem } from '@/lib/types';
import { HotelCard } from './HotelCard';

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

const baseHotel: SearchResultItem = {
  hotel_id: 7,
  canonical_slug: 'rixos-premium',
  name_uk: 'Rixos Premium',
  stars: 5,
  destination_id: 3,
  min_price_uah: 48000,
  deep_link: 'https://operator.test/x',
  requested_nights: 7,
  effective_nights: 7,
  review_score: 9.2,
  last_observed_at: null,
  nights_fallback: false,
  photos: [{ url: 'https://img.test/p.jpg' }],
};

afterEach(() => {
  vi.useRealTimers();
});

describe('HotelCard', () => {
  it('renders name, slug link, "від" price and review score', () => {
    render(<HotelCard hotel={baseHotel} />);
    expect(screen.getByText('Rixos Premium')).toBeInTheDocument();
    expect(screen.getByRole('link')).toHaveAttribute('href', '/hotels/rixos-premium');
    expect(screen.getByText('від')).toBeInTheDocument();
    expect(ws(screen.getByText(/48.000 ₴/).textContent ?? '')).toContain('48 000 ₴');
    expect(screen.getByText('9.2')).toBeInTheDocument();
  });

  it('labels the price-from link with the hotel name and price for a11y', () => {
    render(<HotelCard hotel={baseHotel} />);
    const label = screen.getByRole('link').getAttribute('aria-label') ?? '';
    expect(label).toContain('Rixos Premium');
    expect(ws(label)).toContain('48 000 ₴');
  });

  it('badges a duration-fallback price honestly', () => {
    render(<HotelCard hotel={{ ...baseHotel, nights_fallback: true, effective_nights: 10 }} />);
    expect(screen.getByText(/ціна за 10 ноч\./)).toBeInTheDocument();
  });

  it('falls back to a generic duration note when effective nights is unknown', () => {
    render(<HotelCard hotel={{ ...baseHotel, nights_fallback: true, effective_nights: null }} />);
    expect(screen.getByText(/інша тривалість/)).toBeInTheDocument();
  });

  it('shows a price-age note only when the observation is ≥6h old', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-06-15T12:00:00Z'));

    const { rerender } = render(
      <HotelCard hotel={{ ...baseHotel, last_observed_at: '2026-06-15T11:00:00Z' }} />,
    );
    expect(screen.queryByText(/оновлено/)).toBeNull(); // 1h → fresh

    rerender(<HotelCard hotel={{ ...baseHotel, last_observed_at: '2026-06-15T04:00:00Z' }} />);
    expect(screen.getByText(/оновлено 8 год тому/)).toBeInTheDocument(); // 8h → stale
  });

  it('renders an inline SVG placeholder (not a platform emoji) when there is no photo', () => {
    const { container } = render(<HotelCard hotel={{ ...baseHotel, photos: [] }} />);
    // No <img> for a photoless hotel, and the placeholder is a decorative SVG
    // glyph rather than the OS/font-dependent 🏨 emoji.
    expect(screen.queryByRole('img')).toBeNull();
    expect(screen.queryByText('🏨')).toBeNull();
    const svg = container.querySelector('svg[aria-hidden="true"]');
    expect(svg).not.toBeNull();
  });

  it('puts a `group` class on an ancestor so the image group-hover zoom can fire', () => {
    const { container } = render(<HotelCard hotel={baseHotel} />);
    const img = screen.getByRole('img');
    // The zoom uses group-hover:scale-105, which only resolves under a literal
    // `group` ancestor. Walk up from the image and assert one carries it.
    let node: HTMLElement | null = img.parentElement;
    let hasGroupAncestor = false;
    while (node && node !== container) {
      if (node.classList.contains('group')) {
        hasGroupAncestor = true;
        break;
      }
      node = node.parentElement;
    }
    expect(hasGroupAncestor).toBe(true);
    expect(img.className).toContain('group-hover:scale-105');
  });
});

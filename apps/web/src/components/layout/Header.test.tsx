import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Header } from './Header';

vi.mock('@/lib/api-client', () => ({
  fetchDestinations: vi.fn(async () => []),
}));

describe('Header', () => {
  it('keeps primary routes available in mobile navigation', async () => {
    render(await Header());

    const mobileNav = screen.getByRole('navigation', { name: /Мобільна навігація/i });
    const mobile = within(mobileNav);

    expect(mobileNav).toHaveClass('overflow-x-auto');
    expect(mobile.getByRole('link', { name: 'Пошук' })).toHaveAttribute('href', '/search');
    expect(mobile.getByRole('link', { name: 'Знижки' })).toHaveAttribute('href', '/deals');
    expect(mobile.getByRole('link', { name: 'Дешеві' })).toHaveAttribute('href', '/cheap');
    expect(mobile.getByRole('link', { name: 'Telegram' })).toHaveAttribute('href', '/telegram');
    expect(mobile.getByRole('link', { name: 'Про нас' })).toHaveAttribute('href', '/about');
  });
});

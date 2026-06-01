// Render tests for the hotel detail photo carousel. Locks the accessible
// placeholder branches (null / empty photos), the single-photo case (no
// thumbnail strip), and the multi-photo thumbnail selection (active thumb is
// announced via aria-current and clicking a thumb swaps the main image).
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { HotelPhoto } from '@/lib/types';
import { HotelPhotoCarousel } from './HotelPhotoCarousel';

function photo(url: string, alt?: string): HotelPhoto {
  return { url, alt };
}

describe('HotelPhotoCarousel', () => {
  it('renders an accessible placeholder for null photos', () => {
    render(<HotelPhotoCarousel photos={null} alt="Готель" />);

    expect(screen.getByText('Фото готелю недоступні')).toBeInTheDocument();
    // The placeholder itself carries role="img" + an accessible name; there is
    // no real <img> element with a photo src.
    const placeholder = screen.getByRole('img');
    expect(placeholder).toHaveAccessibleName('Фото готелю недоступне');
    expect(placeholder.tagName).toBe('DIV');
  });

  it('renders the placeholder for an empty photo array', () => {
    render(<HotelPhotoCarousel photos={[]} alt="Готель" />);

    expect(screen.getByText('Фото готелю недоступні')).toBeInTheDocument();
  });

  it('renders a single photo with no thumbnail strip', () => {
    render(<HotelPhotoCarousel photos={[photo('https://cdn.test/a.jpg')]} alt="Готель" />);

    // Only the main image renders (thumbs use alt="" → presentation role).
    const imgs = screen.getAllByRole('img');
    expect(imgs).toHaveLength(1);
    expect(imgs[0]).toHaveAttribute('src', 'https://cdn.test/a.jpg');
    // No thumbnail list.
    expect(screen.queryByRole('list')).toBeNull();
    // No position overlay with a single photo.
    expect(screen.queryByText('1 / 1')).toBeNull();
  });

  it('labels each thumbnail "Фото i з N" and marks the active one', () => {
    render(
      <HotelPhotoCarousel
        photos={[photo('https://cdn.test/a.jpg'), photo('https://cdn.test/b.jpg')]}
        alt="Готель"
      />,
    );

    const first = screen.getByRole('button', { name: 'Фото 1 з 2' });
    const second = screen.getByRole('button', { name: 'Фото 2 з 2' });
    // First thumb is active on mount.
    expect(first).toHaveAttribute('aria-current', 'true');
    expect(second).not.toHaveAttribute('aria-current');
  });

  it('swaps the main image and active thumb when a thumbnail is clicked', () => {
    render(
      <HotelPhotoCarousel
        photos={[photo('https://cdn.test/a.jpg'), photo('https://cdn.test/b.jpg')]}
        alt="Готель"
      />,
    );

    // The single role="img" is the main image (thumbs are alt="" presentation).
    expect(screen.getByRole('img')).toHaveAttribute('src', 'https://cdn.test/a.jpg');

    fireEvent.click(screen.getByRole('button', { name: 'Фото 2 з 2' }));

    expect(screen.getByRole('img')).toHaveAttribute('src', 'https://cdn.test/b.jpg');
    expect(screen.getByRole('button', { name: 'Фото 2 з 2' })).toHaveAttribute(
      'aria-current',
      'true',
    );
    expect(screen.getByRole('button', { name: 'Фото 1 з 2' })).not.toHaveAttribute('aria-current');
  });

  it('shows the position overlay with multiple photos', () => {
    render(
      <HotelPhotoCarousel
        photos={[photo('https://cdn.test/a.jpg'), photo('https://cdn.test/b.jpg')]}
        alt="Готель"
      />,
    );

    expect(screen.getByText('1 / 2')).toBeInTheDocument();
  });
});

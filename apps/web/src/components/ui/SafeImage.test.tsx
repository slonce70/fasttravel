import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SafeImage } from './SafeImage';

describe('SafeImage', () => {
  it('renders fallback text when src is null or blank', () => {
    const { rerender } = render(<SafeImage src={null} alt="Готель" className="h-32 w-full" />);

    expect(screen.getByText('Фото недоступне')).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: 'Готель' })).toBeNull();

    rerender(<SafeImage src="   " alt="Готель" className="h-32 w-full" />);

    expect(screen.getByText('Фото недоступне')).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: 'Готель' })).toBeNull();
  });

  it('switches from image to fallback text when the image errors', () => {
    render(<SafeImage src="https://cdn.test/hotel.jpg" alt="Готель" className="h-32 w-full" />);

    const image = screen.getByRole('img', { name: 'Готель' });
    expect(image).toHaveAttribute('src', 'https://cdn.test/hotel.jpg');
    expect(image).toHaveAttribute('loading', 'lazy');
    expect(screen.queryByText('Фото недоступне')).toBeNull();

    fireEvent.error(image);

    expect(screen.getByText('Фото недоступне')).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: 'Готель' })).toBeNull();
  });

  it('allows eager loading when requested', () => {
    render(
      <SafeImage
        src="https://cdn.test/hotel.jpg"
        alt="Готель"
        className="h-32 w-full"
        loading="eager"
      />,
    );

    expect(screen.getByRole('img', { name: 'Готель' })).toHaveAttribute('loading', 'eager');
  });
});

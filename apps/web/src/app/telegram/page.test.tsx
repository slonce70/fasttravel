import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import TelegramPage from './page';

describe('TelegramPage', () => {
  it('describes the current date-dip detector instead of stale historical-percentile claims', () => {
    render(<TelegramPage />);

    expect(screen.getByText(/сусідні дати/i)).toBeInTheDocument();
    expect(screen.getByText(/від 4%/i)).toBeInTheDocument();
    expect(screen.queryByText(/15%/i)).toBeNull();
    expect(screen.queryByText(/60 днів/i)).toBeNull();
    expect(screen.queryByText(/історичної ціни/i)).toBeNull();
  });
});

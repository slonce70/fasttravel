// Characterization tests for the calendar price-heatmap math. Pure functions
// that decide whether a date cell leans green (cheap) or red (expensive) for
// the whole window. Locks the percentile-rank behaviour (outlier-robust) and
// the exact HSL gradient so a refactor can't silently re-shade the calendar.
import { describe, expect, it } from 'vitest';
import { buildPriceScale, colorForPrice, priceColor, priceRank } from './deal-color';

describe('buildPriceScale', () => {
  it('drops null/zero/negative prices and sorts ascending', () => {
    const scale = buildPriceScale([300, null, 100, 0, 200, -5, undefined]);
    expect(scale.sorted).toEqual([100, 200, 300]);
  });

  it('returns an empty scale when nothing is priced', () => {
    expect(buildPriceScale([null, 0, undefined]).sorted).toEqual([]);
  });
});

describe('priceRank', () => {
  const scale = buildPriceScale([100, 200, 300]);

  it('maps cheapest→0, median→0.5, dearest→1', () => {
    expect(priceRank(scale, 100)).toBe(0);
    expect(priceRank(scale, 200)).toBe(0.5);
    expect(priceRank(scale, 300)).toBe(1);
  });

  it('defaults to the neutral midpoint with <2 data points', () => {
    expect(priceRank(buildPriceScale([]), 100)).toBe(0.5);
    expect(priceRank(buildPriceScale([100]), 100)).toBe(0.5);
  });

  it('returns the neutral midpoint for a flat window (all prices equal)', () => {
    // min === max → no cheap/expensive spread, so the percentile is undefined.
    // It must not paint a flat window the brightest "cheapest" green (rank 0).
    const flat = buildPriceScale([50_000, 50_000, 50_000, 50_000]);
    expect(priceRank(flat, 50_000)).toBe(0.5);
    expect(colorForPrice(flat, 50_000)).toBe(priceColor(0.5));
  });

  it('ranks a value below/above the window outside [0,1] (priceColor clamps)', () => {
    expect(priceRank(scale, 50)).toBe(0);
    expect(priceRank(scale, 500)).toBe(1.5);
  });
});

describe('priceColor', () => {
  it('renders the green→amber→red gradient at the anchors', () => {
    expect(priceColor(0)).toBe('hsl(140.0 70% 88.0%)'); // cheap → green
    expect(priceColor(0.5)).toBe('hsl(72.5 70% 82.0%)'); // mid → amber
    expect(priceColor(1)).toBe('hsl(5.0 70% 76.0%)'); // dear → red
  });

  it('clamps ranks outside [0,1] to the gradient ends', () => {
    expect(priceColor(1.5)).toBe(priceColor(1));
    expect(priceColor(-2)).toBe(priceColor(0));
  });
});

describe('colorForPrice', () => {
  const scale = buildPriceScale([100, 200, 300]);

  it('returns null for a missing price (no cell shading)', () => {
    expect(colorForPrice(scale, null)).toBeNull();
    expect(colorForPrice(scale, undefined)).toBeNull();
  });

  it('shades cheapest green and dearest red', () => {
    expect(colorForPrice(scale, 100)).toBe(priceColor(0));
    expect(colorForPrice(scale, 300)).toBe(priceColor(1));
  });
});

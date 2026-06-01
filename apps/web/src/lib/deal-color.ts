/**
 * Heatmap color computation for calendar cells.
 *
 * Strategy: rank-normalize prices within a single hotel's visible window so
 * that cheap days lean green and expensive days lean red, regardless of the
 * absolute price level (a 5★ Antalya AI and a 3★ Kemer HB both look the same
 * shape of heatmap). We use percentile rank (not min-max) so that a single
 * outlier doesn't compress the rest of the gradient.
 */

export interface ColorScale {
  /** Sorted array of prices (no nulls, no duplicates pruned). */
  sorted: number[];
}

export function buildPriceScale(prices: ReadonlyArray<number | null | undefined>): ColorScale {
  const arr: number[] = [];
  for (const p of prices) {
    if (p != null && p > 0) arr.push(p);
  }
  arr.sort((a, b) => a - b);
  return { sorted: arr };
}

/** Returns 0..1 where 0 = cheapest in window, 1 = most expensive. */
export function priceRank(scale: ColorScale, price: number): number {
  const n = scale.sorted.length;
  if (n === 0) return 0.5;
  if (n === 1) return 0.5;
  // A flat window (all prices equal) has no cheap/expensive spread, so the
  // percentile is undefined — return the neutral midpoint instead of painting
  // every cell the brightest "cheapest" green. Matches the n<=1 fallback.
  if (scale.sorted[0] === scale.sorted[n - 1]) return 0.5;
  // Binary search for first index >= price.
  let lo = 0;
  let hi = n;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if ((scale.sorted[mid] ?? 0) < price) lo = mid + 1;
    else hi = mid;
  }
  return lo / (n - 1);
}

/**
 * HSL color from rank. 0 = green (140°), 0.5 = amber (45°), 1 = red (5°).
 * We use low saturation and high lightness so the cell remains readable
 * with dark text on top.
 */
export function priceColor(rank: number): string {
  // Map 0..1 -> 140..5 (green -> amber -> red).
  const clamped = Math.min(1, Math.max(0, rank));
  const hue = 140 - clamped * 135;
  const saturation = 70;
  // Slight dip in lightness in the middle so amber/yellow doesn't wash out.
  const lightness = 88 - clamped * 12;
  return `hsl(${hue.toFixed(1)} ${saturation}% ${lightness.toFixed(1)}%)`;
}

/**
 * Convenience wrapper: given the full set of visible prices and one specific
 * price, return the matching cell background color.
 */
export function colorForPrice(scale: ColorScale, price: number | null | undefined): string | null {
  if (price == null) return null;
  return priceColor(priceRank(scale, price));
}

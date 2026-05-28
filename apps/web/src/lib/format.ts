/**
 * UA-locale formatting helpers. We deliberately avoid `next-intl` on MVP —
 * the site is single-locale (uk) so the cost/benefit doesn't justify it yet.
 */

// Use a plain number formatter and append "₴" by hand. Default
// uk-UA currency symbol flips between "₴" and "грн" depending on the
// Node.js ICU build, which breaks visual consistency between SSR pages.
const PRICE_FMT = new Intl.NumberFormat('uk-UA', {
  maximumFractionDigits: 0,
});

const PRICE_SHORT_FMT = new Intl.NumberFormat('uk-UA', {
  maximumFractionDigits: 1,
  minimumFractionDigits: 0,
});

const DATE_LONG_FMT = new Intl.DateTimeFormat('uk-UA', { dateStyle: 'long' });
const DATE_MEDIUM_FMT = new Intl.DateTimeFormat('uk-UA', { dateStyle: 'medium' });

/** "22 400 ₴" */
export function formatPrice(uah: number | null | undefined): string {
  if (uah == null) return '—';
  return `${PRICE_FMT.format(uah)} ₴`;
}

/**
 * Compact representation for tight UI like calendar cells: 22400 -> "22.4к",
 * 9800 -> "9.8к", 105000 -> "105к". Always 3-4 chars.
 */
export function formatPriceCompact(uah: number | null | undefined): string {
  if (uah == null) return '—';
  if (uah < 1000) return String(uah);
  const k = uah / 1000;
  // < 10 -> one decimal, >= 10 -> rounded integer to keep width small.
  if (k < 10) return `${PRICE_SHORT_FMT.format(Math.round(k * 10) / 10)}к`;
  return `${Math.round(k)}к`;
}

/** "15 червня 2026 р." */
export function formatDateLong(d: Date | string): string {
  return DATE_LONG_FMT.format(toDate(d));
}

/** "15 черв. 2026 р." */
export function formatDateMedium(d: Date | string): string {
  return DATE_MEDIUM_FMT.format(toDate(d));
}

/** "оновлено 12 хв тому" — relative-time helper. */
export function formatRelativeTime(d: Date | string): string {
  const date = toDate(d);
  const diffSec = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
  if (diffSec < 60) return 'щойно';
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin} ${plural(diffMin, 'хвилину', 'хвилини', 'хвилин')} тому`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr} ${plural(diffHr, 'годину', 'години', 'годин')} тому`;
  const diffDay = Math.round(diffHr / 24);
  if (diffDay < 7) return `${diffDay} ${plural(diffDay, 'день', 'дні', 'днів')} тому`;
  return formatDateMedium(date);
}

function toDate(d: Date | string): Date {
  return typeof d === 'string' ? new Date(d) : d;
}

/** Ukrainian pluralization: 1 → form1, 2-4 → form2-4, 5+ → form5+. */
export function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few;
  return many;
}

/** "7 ночей" / "10 ночей" / "1 ніч" */
export function formatNights(n: number): string {
  return `${n} ${plural(n, 'ніч', 'ночі', 'ночей')}`;
}

const MEAL_PLAN_UK: Record<string, string> = {
  AI: 'Все включено',
  UAI: 'Ультра все включено',
  HB: 'Сніданок + вечеря',
  BB: 'Сніданок',
  FB: 'Сніданок, обід, вечеря',
  RO: 'Без харчування',
};

export function formatMealPlan(code: string): string {
  return MEAL_PLAN_UK[code.toUpperCase()] ?? code;
}

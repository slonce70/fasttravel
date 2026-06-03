// Characterization tests for the web deal-signal copy map. This is the
// honesty contract on the frontend: the struck-through baseline (implying a
// real former price) must appear for promo_discount ONLY — every comparison
// method renders a non-struck reference. Locks the per-method copy and that
// invariant so a future edit can't quietly reintroduce a fake "was X" price.
import { describe, expect, it } from 'vitest';
import type { Deal } from './types';
import { getDealSignalCopy } from './deal-signal';

const sig = (m: string) => getDealSignalCopy(m as Deal['detection_method']);
const nullSig = () => getDealSignalCopy(null as unknown as Deal['detection_method']);

describe('getDealSignalCopy', () => {
  it('calendar_anomaly → neighbouring-dates copy, no strike', () => {
    expect(sig('calendar_anomaly')).toEqual({
      badgeIcon: 'Дата',
      badgeVariant: 'success',
      reason: 'Ця дата значно дешевша за сусідні у цьому готелі',
      baselineLabel: 'інші дати',
      strikeBaseline: false,
    });
  });

  it('promo_discount → operator strike-through copy, struck baseline', () => {
    expect(sig('promo_discount')).toEqual({
      badgeIcon: 'Акція',
      badgeVariant: 'accent',
      reason: 'Спецціна від оператора — обмежена пропозиція',
      baselineLabel: 'ціна оператора до акції',
      strikeBaseline: true,
    });
  });

  it('peer_anomaly → similar-hotels copy, no strike', () => {
    expect(sig('peer_anomaly')).toMatchObject({
      badgeIcon: 'Регіон',
      badgeVariant: 'neutral',
      baselineLabel: 'орієнтир схожих',
      strikeBaseline: false,
    });
  });

  it('percentile → same-hotel history copy, no strike', () => {
    expect(sig('percentile')).toMatchObject({
      badgeIcon: 'Історія',
      badgeVariant: 'brand',
      baselineLabel: 'зазвичай',
      strikeBaseline: false,
    });
  });

  it('is case-insensitive and trims surrounding whitespace', () => {
    expect(sig('  PROMO_DISCOUNT ').strikeBaseline).toBe(true);
    expect(sig('Calendar_Anomaly').baselineLabel).toBe('інші дати');
  });

  it('unknown non-empty method → neutral price-reference, no strike', () => {
    expect(sig('legacy_experiment')).toMatchObject({
      badgeIcon: 'Орієнтир',
      badgeVariant: 'neutral',
      baselineLabel: 'орієнтир',
      strikeBaseline: false,
    });
  });

  it('empty / blank / null method → same-hotel "зазвичай" fallback, no strike', () => {
    expect(sig('')).toMatchObject({ baselineLabel: 'зазвичай', strikeBaseline: false });
    expect(sig('   ')).toMatchObject({ baselineLabel: 'зазвичай', strikeBaseline: false });
    expect(nullSig()).toMatchObject({ baselineLabel: 'зазвичай', strikeBaseline: false });
  });

  it('strikes the baseline for promo_discount ONLY (honesty invariant)', () => {
    for (const m of [
      'calendar_anomaly',
      'peer_anomaly',
      'percentile',
      'legacy_experiment',
      '',
      '   ',
    ]) {
      expect(sig(m).strikeBaseline).toBe(false);
    }
    expect(nullSig().strikeBaseline).toBe(false);
    expect(sig('promo_discount').strikeBaseline).toBe(true);
  });
});

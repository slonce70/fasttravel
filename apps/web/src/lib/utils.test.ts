// Characterization tests for the generic utils: the in-house `cn` class
// merger (recurses strings/arrays/objects, drops falsy) and the date/hash
// helpers used by search params, the calendar and skeleton placeholders.
import { describe, expect, it } from 'vitest';
import { addDays, cn, diffDays, isoDate, stringHash } from './utils';

describe('cn', () => {
  it('joins truthy strings/numbers and drops falsy values', () => {
    expect(cn('a', 'b')).toBe('a b');
    expect(cn('a', false, null, undefined, '', 'c')).toBe('a c');
    expect(cn(0, 1, 'x')).toBe('1 x'); // 0 is falsy → dropped
    expect(cn()).toBe('');
  });

  it('expands object maps by truthy key and recurses arrays', () => {
    expect(cn('a', { b: true, c: false })).toBe('a b');
    expect(cn('a', ['b', ['c', { d: true, e: false }]])).toBe('a b c d');
  });
});

describe('date helpers', () => {
  it('isoDate formats local Y-M-D with zero padding', () => {
    expect(isoDate(new Date(2026, 5, 9))).toBe('2026-06-09');
    expect(isoDate(new Date(2026, 11, 31))).toBe('2026-12-31');
  });

  it('addDays returns a new date and crosses month boundaries', () => {
    const d = new Date(2026, 5, 28); // 28 June
    expect(isoDate(addDays(d, 5))).toBe('2026-07-03');
    expect(isoDate(d)).toBe('2026-06-28'); // original not mutated
  });

  it('diffDays counts whole days, signed', () => {
    expect(diffDays(new Date(2026, 5, 9), new Date(2026, 5, 16))).toBe(7);
    expect(diffDays(new Date(2026, 5, 16), new Date(2026, 5, 9))).toBe(-7);
  });
});

describe('stringHash', () => {
  it('is deterministic and non-negative', () => {
    expect(stringHash('abc')).toBe(stringHash('abc'));
    expect(stringHash('')).toBe(0);
    expect(stringHash('rixos-premium')).toBeGreaterThanOrEqual(0);
  });

  it('separates distinct inputs', () => {
    expect(stringHash('abc')).not.toBe(stringHash('abd'));
  });
});

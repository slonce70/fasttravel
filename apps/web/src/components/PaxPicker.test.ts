import { describe, expect, it } from 'vitest';
import { DEFAULT_PAX, paxFromSearchParams, paxToSearchParams } from './PaxPicker';

function getFrom(params: Record<string, string | null>) {
  return (key: string) => params[key] ?? null;
}

describe('paxFromSearchParams', () => {
  it('accepts the API-supported six-kid boundary', () => {
    expect(paxFromSearchParams(getFrom({ adults: '9', kids: '1,2,3,4,5,17' }))).toEqual({
      adults: 9,
      kids: [1, 2, 3, 4, 5, 17],
    });
  });

  it('falls back to displayed defaults for pax values the API will reject', () => {
    expect(paxFromSearchParams(getFrom({ adults: '10', kids: '1,2,3,4,5,6,7' }))).toEqual(
      DEFAULT_PAX,
    );
    expect(paxFromSearchParams(getFrom({ adults: '7.5', kids: '7,nope' }))).toEqual(DEFAULT_PAX);
  });
});

describe('paxToSearchParams', () => {
  it('serializes sanitized pax values', () => {
    const qs = new URLSearchParams();

    paxToSearchParams(qs, { adults: 3, kids: [7, 12] });

    expect(qs.toString()).toBe('adults=3&kids=7%2C12');
  });
});

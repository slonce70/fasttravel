import { describe, expect, it } from 'vitest';
import type { Offer } from '@/lib/types';
import { offerKey } from './OffersList';

const offer: Offer = {
  operator_id: 1,
  operator_code: 'farvater',
  check_in: '2026-07-01',
  nights: 7,
  meal_plan: 'AI',
  room_category: 'Standard',
  price_uah: 42000,
  price_original: 1000,
  currency: 'USD',
  deep_link: 'https://example.test/standard',
  observed_at: '2026-05-28T00:00:00Z',
};

describe('offerKey', () => {
  it('keeps room variants distinct for the same operator/date/meal', () => {
    const suite = {
      ...offer,
      room_category: 'Suite',
      price_uah: 51000,
      deep_link: 'https://example.test/suite',
    };

    expect(offerKey(offer)).not.toEqual(offerKey(suite));
  });
});

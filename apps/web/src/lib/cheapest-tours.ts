import type { CheapestTour } from './types';

/** One country's group of cheapest tours, ranks preserved in API order. */
export interface CheapestTourGroup {
  country_iso2: string;
  /** Resolved country display name; falls back to the ISO2 code when null. */
  country_name: string;
  tours: CheapestTour[];
}

/**
 * Groups the FLAT ranked list returned by `/api/cheapest-tours` by country,
 * preserving the server's ordering (country_name → rank → hotel_id). A Map
 * keeps insertion order, so countries come out in name order and each group's
 * tours stay in rank order. We deliberately do NOT re-sort or slice — stars≥3,
 * the +3..+90 lookahead, the freshness gate and the TOP-N cut are all enforced
 * server-side; sparse countries legitimately return fewer than N hotels.
 */
export function groupByCountry(tours: CheapestTour[]): CheapestTourGroup[] {
  const groups = new Map<string, CheapestTourGroup>();
  for (const tour of tours) {
    let group = groups.get(tour.country_iso2);
    if (!group) {
      group = {
        country_iso2: tour.country_iso2,
        country_name: tour.country_name ?? tour.country_iso2,
        tours: [],
      };
      groups.set(tour.country_iso2, group);
    }
    group.tours.push(tour);
  }
  return [...groups.values()];
}

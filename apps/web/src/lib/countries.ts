import type { CountryOut } from '@/lib/types';

// Selector fallback only: keeps search/deals usable when the live
// `/api/destinations` catalog is temporarily empty. Order mirrors
// apps/scheduler/src/clients/farvater_runtime.py::CATALOG_COUNTRIES.
export const CORE_COUNTRIES: CountryOut[] = [
  {
    id: -1,
    country_iso2: 'TR',
    country_slug: 'turkey',
    name_uk: 'Туреччина',
    name_en: 'Turkey',
    hotel_count: 0,
    regions: [],
  },
  {
    id: -2,
    country_iso2: 'EG',
    country_slug: 'egypt',
    name_uk: 'Єгипет',
    name_en: 'Egypt',
    hotel_count: 0,
    regions: [],
  },
  {
    id: -3,
    country_iso2: 'AE',
    country_slug: 'uae',
    name_uk: 'ОАЕ',
    name_en: 'United Arab Emirates',
    hotel_count: 0,
    regions: [],
  },
  {
    id: -4,
    country_iso2: 'GR',
    country_slug: 'greece',
    name_uk: 'Греція',
    name_en: 'Greece',
    hotel_count: 0,
    regions: [],
  },
  {
    id: -5,
    country_iso2: 'ES',
    country_slug: 'spain',
    name_uk: 'Іспанія',
    name_en: 'Spain',
    hotel_count: 0,
    regions: [],
  },
  {
    id: -6,
    country_iso2: 'BG',
    country_slug: 'bulgaria',
    name_uk: 'Болгарія',
    name_en: 'Bulgaria',
    hotel_count: 0,
    regions: [],
  },
  {
    id: -7,
    country_iso2: 'TH',
    country_slug: 'thailand',
    name_uk: 'Таїланд',
    name_en: 'Thailand',
    hotel_count: 0,
    regions: [],
  },
  {
    id: -8,
    country_iso2: 'CY',
    country_slug: 'cyprus',
    name_uk: 'Кіпр',
    name_en: 'Cyprus',
    hotel_count: 0,
    regions: [],
  },
  {
    id: -9,
    country_iso2: 'HR',
    country_slug: 'croatia',
    name_uk: 'Хорватія',
    name_en: 'Croatia',
    hotel_count: 0,
    regions: [],
  },
  {
    id: -10,
    country_iso2: 'ME',
    country_slug: 'montenegro',
    name_uk: 'Чорногорія',
    name_en: 'Montenegro',
    hotel_count: 0,
    regions: [],
  },
  {
    id: -11,
    country_iso2: 'MV',
    country_slug: 'maldives',
    name_uk: 'Мальдіви',
    name_en: 'Maldives',
    hotel_count: 0,
    regions: [],
  },
];

// Ukrainian accusative case for country names (for "Знайти тури в <country>"
// labels). Falls back to the nominative for any country not listed.
const ACCUSATIVE: Record<string, string> = {
  Туреччина: 'Туреччину',
  Єгипет: 'Єгипет',
  ОАЕ: 'ОАЕ',
  Греція: 'Грецію',
  Іспанія: 'Іспанію',
  Болгарія: 'Болгарію',
  Чорногорія: 'Чорногорію',
  Хорватія: 'Хорватію',
  Кіпр: 'Кіпр',
  Таїланд: 'Таїланд',
  Мальдіви: 'Мальдіви',
  Італія: 'Італію',
  Туніс: 'Туніс',
  'Домініканська Республіка': 'Домініканську Республіку',
  Україна: 'Україну',
};

export function accusativeCountry(name: string): string {
  return ACCUSATIVE[name] ?? name;
}

// Collapse rows that share a country_iso2 (the catalog can carry the same
// country under multiple operators), keeping the first occurrence and the
// upstream sort order.
export function uniqueCountriesByIso(countries: CountryOut[]): CountryOut[] {
  const seen = new Set<string>();
  return countries.filter((country) => {
    const iso = country.country_iso2.toUpperCase();
    if (seen.has(iso)) return false;
    seen.add(iso);
    return true;
  });
}

export function countriesForSelector(countries: CountryOut[]): CountryOut[] {
  return uniqueCountriesByIso([...countries, ...CORE_COUNTRIES]);
}

import type { CountryOut } from '@/lib/types';

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

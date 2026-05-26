import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { Suspense } from 'react';

import { Container } from '@/components/layout/Container';
import { DealCard } from '@/components/DealCard';
import { HotelCard } from '@/components/HotelCard';
import { SearchForm } from '@/components/SearchForm';
import { fetchDeals, fetchDestination, fetchDestinations, searchHotels } from '@/lib/api-client';
import type { CountryOut, Deal } from '@/lib/types';

/**
 * SEO landing page for one country — /destinations/turkey, /destinations/egypt …
 *
 * Statically generated at build time from `fetchDestinations()` so each
 * country gets a real prerendered HTML file. ISR (1h) refreshes the hotel
 * count and featured deals without a full rebuild.
 */

export const revalidate = 3600;

export async function generateStaticParams() {
  try {
    const countries = await fetchDestinations({ revalidate: 3600 });
    return countries.map((c) => ({ country: c.country_slug }));
  } catch {
    // If the API is unreachable at build time we'd rather ship zero static
    // pages than fail the whole build — the dynamic fallback still works.
    return [];
  }
}

function accusative(name: string): string {
  const map: Record<string, string> = {
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
  return map[name] ?? name;
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ country: string }>;
}): Promise<Metadata> {
  const { country: slug } = await params;
  const country = await fetchDestination(slug).catch(() => null);
  if (!country) {
    return { title: 'Напрямок не знайдено' };
  }
  return {
    title: `Тури в ${accusative(country.name_uk)} — календар цін на 90 днів`,
    description: `${country.name_uk} на FastTravel. Дивіться календар цін на ${country.hotel_count} готелів у каталозі від трьох операторів.`,
  };
}

async function getFeaturedDeals(iso2: string): Promise<Deal[]> {
  try {
    const page = await fetchDeals({ country: iso2, limit: 6 }, { revalidate: 600 });
    return page.items;
  } catch {
    return [];
  }
}

async function getCountriesList(): Promise<CountryOut[]> {
  try {
    return await fetchDestinations({ revalidate: 3600 });
  } catch {
    return [];
  }
}

export default async function CountryDestinationPage({
  params,
}: {
  params: Promise<{ country: string }>;
}) {
  const { country: slug } = await params;

  const country = await fetchDestination(slug, { revalidate: 3600 });
  if (!country) notFound();

  const [results, deals, countries] = await Promise.all([
    searchHotels(
      { country: country.country_iso2, sort: 'rating_desc', limit: 50 },
      { revalidate: 3600 },
    ).catch(() => ({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    })),
    getFeaturedDeals(country.country_iso2),
    getCountriesList(),
  ]);

  const hasHotels = country.hotel_count > 0;
  const accName = accusative(country.name_uk);

  return (
    <div className="space-y-10 pb-12">
      <section className="bg-gradient-to-br from-brand-700 to-brand-900 py-10 text-white">
        <Container>
          <nav aria-label="Хлібні крихти" className="mb-3 text-xs text-brand-100">
            <Link href="/" className="hover:underline">
              Головна
            </Link>
            <span aria-hidden> · </span>
            <span>Напрямки</span>
            <span aria-hidden> · </span>
            <span className="text-white">{country.name_uk}</span>
          </nav>
          <h1 className="text-3xl font-bold sm:text-4xl">Тури в {accName}</h1>
          <p className="mt-2 max-w-2xl text-brand-100">
            {hasHotels
              ? `${country.hotel_count} готелів у каталозі. Календар цін показує мінімальні ціни на 90 днів вперед від трьох операторів.`
              : `Готуємо каталог готелів у країні «${country.name_uk}». Календар цін з’явиться найближчим часом.`}
          </p>
          <div className="mt-6">
            <Suspense fallback={<div className="h-44 rounded-2xl bg-white/10" />}>
              <SearchForm countries={countries} defaultCountry={country.country_iso2} />
            </Suspense>
          </div>
        </Container>
      </section>

      {!hasHotels ? (
        <Container>
          <div className="rounded-xl bg-white p-10 text-center ring-1 ring-slate-200">
            <p className="text-base font-semibold text-slate-900">Поки немає готелів у каталозі</p>
            <p className="mt-2 text-sm text-slate-500">
              Слідкуй за оновленнями — підпишись на Telegram-канал, і ми пришлемо перші тури в цей
              напрямок одразу як вони з’являться.
            </p>
            <Link
              href="/telegram"
              className="mt-4 inline-flex h-10 items-center justify-center rounded-lg bg-accent-500 px-4 text-sm font-semibold text-white transition-colors hover:bg-accent-600"
            >
              Підписатись на Telegram →
            </Link>
          </div>
        </Container>
      ) : (
        <Container className="space-y-10">
          {country.regions.length > 0 && (
            <section aria-labelledby="regions-heading">
              <h2 id="regions-heading" className="mb-4 text-2xl font-bold text-slate-900">
                Курорти {country.name_uk === 'Україна' ? 'України' : country.name_uk}
              </h2>
              <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-3">
                {country.regions.map((r) => (
                  <div key={r.id} className="rounded-xl bg-white p-4 ring-1 ring-slate-200">
                    <h3 className="text-base font-semibold text-slate-900">{r.name_uk}</h3>
                    <p className="mt-1 text-xs text-slate-500">
                      {r.hotel_count > 0
                        ? `${r.hotel_count} готелів у каталозі`
                        : 'Каталог наповнюється'}
                    </p>
                  </div>
                ))}
              </div>
              <p className="mt-3 text-xs text-slate-400">
                Інтерактивна карта регіонів — у Phase 2.
              </p>
            </section>
          )}

          {deals.length > 0 && (
            <section aria-labelledby="deals-heading">
              <div className="mb-4 flex items-end justify-between">
                <h2 id="deals-heading" className="text-2xl font-bold text-slate-900">
                  Гарячі знижки
                </h2>
                <Link
                  href={`/deals?country=${country.country_iso2}`}
                  className="text-sm font-medium text-brand-700 hover:text-brand-900"
                >
                  Усі знижки →
                </Link>
              </div>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {deals.map((d) => (
                  <DealCard key={d.id} deal={d} />
                ))}
              </div>
            </section>
          )}

          <section aria-labelledby="top-hotels-heading">
            <h2 id="top-hotels-heading" className="mb-4 text-2xl font-bold text-slate-900">
              Топ готелів за рейтингом
            </h2>
            {results.items.length === 0 ? (
              <div className="rounded-xl bg-white p-10 text-center text-sm text-slate-500 ring-1 ring-slate-200">
                Каталог ще наповнюється.
              </div>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {results.items.map((h) => (
                  <HotelCard key={h.hotel_id} hotel={h} />
                ))}
              </div>
            )}
          </section>
        </Container>
      )}
    </div>
  );
}

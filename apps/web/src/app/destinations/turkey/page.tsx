import type { Metadata } from 'next';
import { Suspense } from 'react';
import { Container } from '@/components/layout/Container';
import { HotelCard } from '@/components/HotelCard';
import { SearchForm } from '@/components/SearchForm';
import { searchHotels } from '@/lib/api-client';

export const metadata: Metadata = {
  title: 'Тури в Туреччину — календар цін на 90 днів',
  description:
    'Туреччина — головний напрямок FastTravel. Дивіться календар цін на тури по всіх популярних готелях Анталії, Кемера, Белека.',
};

export const revalidate = 3600;

const REGIONS = [
  { name: 'Анталія', desc: 'Центр Турецької Рів’єри' },
  { name: 'Кемер', desc: 'Гори і сосни біля моря' },
  { name: 'Белек', desc: 'Преміум-готелі та поля для гольфу' },
  { name: 'Сіде', desc: 'Античні руїни та довгі пляжі' },
  { name: 'Аланія', desc: 'Бюджетна альтернатива з нічним життям' },
  { name: 'Бодрум', desc: 'Егейське море, для тих хто любить яхти' },
];

export default async function TurkeyDestinationPage() {
  let results;
  try {
    results = await searchHotels({ country: 'TR', limit: 50 }, { revalidate: 3600 });
  } catch {
    results = { items: [], total: 0, limit: 50, offset: 0 };
  }

  return (
    <div className="space-y-10 pb-12">
      <section className="bg-gradient-to-br from-brand-700 to-brand-900 py-10 text-white">
        <Container>
          <h1 className="text-3xl font-bold sm:text-4xl">Тури в Туреччину</h1>
          <p className="mt-2 max-w-2xl text-brand-100">
            {results.total} готелів у каталозі. Календар цін показує мінімальні
            ціни на 90 днів вперед від трьох операторів.
          </p>
          <div className="mt-6">
            <Suspense fallback={<div className="h-44 rounded-2xl bg-white/10" />}>
              <SearchForm />
            </Suspense>
          </div>
        </Container>
      </section>

      <Container className="space-y-10">
        <section aria-labelledby="regions-heading">
          <h2 id="regions-heading" className="mb-4 text-2xl font-bold text-slate-900">
            Курорти Туреччини
          </h2>
          <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-3">
            {REGIONS.map((r) => (
              <div
                key={r.name}
                className="rounded-xl bg-white p-4 ring-1 ring-slate-200"
              >
                <h3 className="text-base font-semibold text-slate-900">{r.name}</h3>
                <p className="mt-1 text-xs text-slate-500">{r.desc}</p>
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs text-slate-400">
            Інтерактивна карта регіонів — у Phase 2.
          </p>
        </section>

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
    </div>
  );
}

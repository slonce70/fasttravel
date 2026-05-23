import Link from 'next/link';
import { Suspense } from 'react';
import { fetchDeals } from '@/lib/api-client';
import { Container } from '@/components/layout/Container';
import { SearchForm } from '@/components/SearchForm';
import { DealCard } from '@/components/DealCard';
import { TelegramCta } from '@/components/TelegramCta';
import type { Deal } from '@/lib/types';

// Revalidate every 10 min — featured deals refresh hourly on the backend.
export const revalidate = 600;

async function getFeaturedDeals(): Promise<Deal[]> {
  try {
    const page = await fetchDeals({ limit: 6 }, { revalidate: 600 });
    return page.items;
  } catch {
    // Don't crash the homepage on a transient backend hiccup.
    return [];
  }
}

export default async function HomePage() {
  const deals = await getFeaturedDeals();

  return (
    <div className="flex flex-col gap-12 pb-12">
      {/* Hero */}
      <section className="bg-gradient-to-br from-brand-700 via-brand-800 to-brand-900 pb-12 pt-12 text-white">
        <Container>
          <h1 className="text-3xl font-bold leading-tight text-balance sm:text-5xl">
            Календар цін на тури в&nbsp;Туреччину
          </h1>
          <p className="mt-3 max-w-2xl text-sm text-brand-100 sm:text-lg">
            Дивись як змінюється ціна тура по днях у одній сітці. Знаходь дні зі
            знижкою -20% і більше — і одразу йди до оператора.
          </p>
          <div className="mt-6 sm:mt-8">
            {/* useSearchParams() inside SearchForm requires Suspense in Next 15
                — otherwise the page is forced to dynamic and ISR is lost. */}
            <Suspense fallback={<div className="h-44 rounded-2xl bg-white/10" />}>
              <SearchForm />
            </Suspense>
          </div>
        </Container>
      </section>

      {/* Featured deals */}
      <Container>
        <div className="mb-5 flex items-end justify-between">
          <h2 className="text-2xl font-bold text-slate-900">Гарячі знижки сьогодні</h2>
          <Link
            href="/deals"
            className="text-sm font-medium text-brand-700 hover:text-brand-900"
          >
            Усі знижки →
          </Link>
        </div>
        {deals.length === 0 ? (
          <div className="rounded-xl bg-white p-10 text-center text-sm text-slate-500 ring-1 ring-slate-200">
            Поки немає виявлених знижок. Зайдіть пізніше або підпишіться на Telegram-канал.
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {deals.map((d) => (
              <DealCard key={d.id} deal={d} />
            ))}
          </div>
        )}
      </Container>

      {/* Telegram CTA */}
      <Container>
        <TelegramCta />
      </Container>

      {/* Three reasons */}
      <Container>
        <h2 className="mb-6 text-2xl font-bold text-slate-900">Чому FastTravel</h2>
        <div className="grid gap-4 md:grid-cols-3">
          <Reason
            title="Календар цін, а не таблиця"
            body="Бачите 90 днів вперед у єдиній сітці кольорів — від зелених дешевих до червоних дорогих."
          />
          <Reason
            title="Знижки знаходить статистика"
            body="Наша система відстежує історію цін кожного готелю і помічає аномалії автоматично."
          />
          <Reason
            title="Чесно: ми не продаємо"
            body="Ми інформаційний агрегатор. Купівля відбувається у туроператора напряму — без націнок."
          />
        </div>
      </Container>
    </div>
  );
}

function Reason({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-xl bg-white p-6 ring-1 ring-slate-200">
      <h3 className="text-base font-semibold text-slate-900">{title}</h3>
      <p className="mt-2 text-sm text-slate-600">{body}</p>
    </div>
  );
}

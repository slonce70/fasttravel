import Link from 'next/link';
import { Suspense } from 'react';
import { fetchDeals, fetchDestinations } from '@/lib/api-client';
import { Container } from '@/components/layout/Container';
import { SearchForm } from '@/components/SearchForm';
import { DealCard } from '@/components/DealCard';
import { TelegramCta } from '@/components/TelegramCta';
import { cn } from '@/lib/utils';
import type { CountryOut, Deal } from '@/lib/types';

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

async function getCountries(): Promise<CountryOut[]> {
  try {
    return await fetchDestinations({ revalidate: 3600 });
  } catch {
    return [];
  }
}

export default async function HomePage() {
  const [deals, countries] = await Promise.all([getFeaturedDeals(), getCountries()]);
  const heroPhoto = deals.find((deal) => deal.hotel_photo_url)?.hotel_photo_url ?? null;
  const heroDeal = deals[0];

  return (
    <div className="flex flex-col gap-14 pb-14">
      <section className="overflow-hidden bg-white">
        <Container className="py-8 sm:py-10 lg:py-12">
          <div className="grid items-center gap-8 lg:grid-cols-[0.92fr_1.08fr]">
            <div>
              <p className="mb-4 text-sm font-semibold text-teal-700">Календар цін на тури</p>
              <h1 className="max-w-3xl text-balance text-4xl font-bold leading-[0.98] tracking-tight text-slate-950 sm:text-5xl">
                Дешеві дати для моря видно до бронювання
              </h1>
              <p className="mt-5 max-w-2xl text-base leading-7 text-slate-600 sm:text-lg">
                Оберіть напрямок, склад туристів і бюджет — FastTravel покаже календар цін,
                підсвітить цікаві дати та дасть перейти до оператора без прихованої націнки.
              </p>
              <div className="mt-7">
                {/* useSearchParams() inside SearchForm requires Suspense in Next 15
                    — otherwise the page is forced to dynamic and ISR is lost. */}
                <Suspense
                  fallback={
                    <div
                      className="h-[392px] animate-pulse rounded-xl bg-slate-100 sm:h-[336px] lg:h-[260px]"
                      aria-hidden
                    />
                  }
                >
                  <SearchForm countries={countries} variant="hero" />
                </Suspense>
              </div>
            </div>
            <TravelDataPreview heroPhoto={heroPhoto} heroDeal={heroDeal} />
          </div>
        </Container>
      </section>

      <Container>
        <div className="mb-5 flex items-end justify-between gap-4">
          <div>
            <p className="text-sm font-semibold text-teal-700">Живі приклади</p>
            <h2 className="mt-1 text-2xl font-bold tracking-tight text-slate-950">
              Гарячі дати й чесні цінові сигнали
            </h2>
          </div>
          <Link href="/deals" className="text-sm font-semibold text-teal-700 hover:text-teal-900">
            Усі знижки →
          </Link>
        </div>
        {deals.length === 0 ? (
          <div className="rounded-xl bg-white p-10 text-center text-sm text-slate-500 ring-1 ring-slate-200">
            Поки немає виявлених знижок. Зайдіть пізніше або підпишіться на Telegram-канал.
          </div>
        ) : (
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {deals.map((d) => (
              <DealCard key={d.id} deal={d} />
            ))}
          </div>
        )}
      </Container>

      <Container>
        <TelegramCta />
      </Container>

      <Container>
        <h2 className="mb-6 text-2xl font-bold tracking-tight text-slate-950">Чому FastTravel</h2>
        <div className="grid gap-4 md:grid-cols-[1.1fr_0.9fr_1fr]">
          <Reason
            title="Календар цін, а не таблиця"
            body="Бачите 90 днів вперед у єдиній сітці кольорів — від зелених дешевих до червоних дорогих."
          />
          <Reason
            title="Знижки знаходить статистика"
            body="Система відстежує історію цін кожного готелю і помічає аномалії автоматично."
          />
          <Reason
            title="Чесно: ми не продаємо"
            body="FastTravel — інформаційний агрегатор. Купівля відбувається у туроператора напряму."
          />
        </div>
      </Container>
    </div>
  );
}

function TravelDataPreview({ heroPhoto, heroDeal }: { heroPhoto: string | null; heroDeal?: Deal }) {
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-[0.82fr_1.18fr]">
        <div className="relative min-h-64 overflow-hidden rounded-xl bg-slate-100 ring-1 ring-slate-200">
          {heroPhoto ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={heroPhoto}
              alt=""
              className="h-full min-h-64 w-full object-cover"
              loading="eager"
            />
          ) : (
            <div className="h-full min-h-64 bg-[linear-gradient(135deg,#dff5ef,#eaf2ff_48%,#fff7ed)]" />
          )}
          <div className="bg-white/92 absolute bottom-3 left-3 right-3 rounded-lg p-3 shadow-sm ring-1 ring-white/80 backdrop-blur">
            <p className="text-xs font-semibold uppercase tracking-wide text-teal-700">
              Travel + Data
            </p>
            <p className="mt-1 text-sm font-semibold text-slate-950">
              Фото для бажання поїхати, календар для рішення.
            </p>
          </div>
        </div>
        <div className="rounded-xl bg-white p-4 shadow-[0_24px_70px_-34px_rgba(15,23,42,0.55)] ring-1 ring-slate-200">
          <div className="mb-4 flex items-start justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-slate-950">Туреччина · липень 2026</p>
              <p className="mt-1 text-xs text-slate-500">
                7-10 ночей · 2 дорослих · будь-яке харчування
              </p>
            </div>
            <Link
              href="/search"
              className="text-xs font-semibold text-teal-700 hover:text-teal-900"
            >
              Відкрити пошук
            </Link>
          </div>
          <HeroCalendarGrid />
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-xs text-slate-500">
            <div className="flex items-center gap-2">
              <span>дешево</span>
              <span className="h-2 w-24 rounded-full bg-gradient-to-r from-teal-600 via-lime-300 to-rose-300" />
              <span>дорого</span>
            </div>
            <span className="font-medium text-teal-700">ціна нижча за сусідні дати</span>
          </div>
        </div>
      </div>
      {heroDeal && (
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <Link
            href={`/hotels/${heroDeal.hotel_slug}`}
            className="rounded-xl bg-slate-50 p-3 ring-1 ring-slate-200 transition-colors hover:bg-white"
          >
            <p className="line-clamp-1 text-sm font-semibold text-slate-900">
              {heroDeal.hotel_name_uk}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              {heroDeal.destination_name ?? 'напрямок уточнюється'}
            </p>
            <p className="mt-3 text-lg font-bold text-teal-800">
              від {new Intl.NumberFormat('uk-UA').format(heroDeal.price_uah)} ₴
            </p>
          </Link>
          <Link
            href="/deals"
            className="rounded-xl bg-slate-50 p-3 ring-1 ring-slate-200 transition-colors hover:bg-white sm:col-span-2"
          >
            <p className="text-sm font-semibold text-slate-900">Дивіться більше живих сигналів</p>
            <p className="mt-1 text-xs text-slate-500">
              Кожна картка пояснює, чому дата виглядає цікавою.
            </p>
          </Link>
        </div>
      )}
    </div>
  );
}

function HeroCalendarGrid() {
  const cells = [
    ['29', '42 910', 'neutral'],
    ['30', '38 600', 'warm'],
    ['1', '28 640', 'cheap'],
    ['2', '31 870', 'cheap'],
    ['3', '44 070', 'warm'],
    ['4', '52 900', 'high'],
    ['5', '49 260', 'high'],
    ['6', '39 210', 'warm'],
    ['7', '35 480', 'cheap'],
    ['8', '33 900', 'cheap'],
    ['9', '46 200', 'warm'],
    ['10', '58 410', 'high'],
    ['11', '41 300', 'warm'],
    ['12', '29 760', 'selected'],
    ['13', '37 820', 'warm'],
    ['14', '43 010', 'neutral'],
    ['15', '32 500', 'cheap'],
    ['16', '36 200', 'cheap'],
    ['17', '48 900', 'high'],
    ['18', '45 260', 'warm'],
    ['19', '34 700', 'cheap'],
  ] as const;

  return (
    <div className="grid grid-cols-7 gap-1.5">
      {cells.map(([day, price, tone]) => (
        <div
          key={`${day}-${price}`}
          className={cn(
            'min-h-14 rounded-lg border p-1.5 text-left',
            tone === 'selected'
              ? 'border-teal-700 bg-teal-700 text-white shadow-sm'
              : tone === 'cheap'
                ? 'border-emerald-200 bg-emerald-50 text-slate-900'
                : tone === 'warm'
                  ? 'border-lime-200 bg-lime-50 text-slate-900'
                  : tone === 'high'
                    ? 'border-rose-100 bg-rose-50 text-slate-900'
                    : 'border-slate-200 bg-slate-50 text-slate-500',
          )}
        >
          <span className="block text-xs font-semibold">{day}</span>
          <span className="mt-1 block text-[10px] font-medium leading-none">{price} ₴</span>
        </div>
      ))}
    </div>
  );
}

function Reason({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-slate-200/80">
      <h3 className="text-base font-semibold text-slate-900">{title}</h3>
      <p className="mt-2 text-sm text-slate-600">{body}</p>
    </div>
  );
}

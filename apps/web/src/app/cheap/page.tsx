import type { Metadata } from 'next';
import { Container } from '@/components/layout/Container';
import { CheapestTourCard } from '@/components/CheapestTourCard';
import { fetchCheapestTours, userMessageForApiError } from '@/lib/api-client';
import { groupByCountry } from '@/lib/cheapest-tours';

export const metadata: Metadata = {
  title: 'Найдешевші тури по напрямках',
  description:
    'Найдешевші доступні тури до Туреччини, Єгипту, Болгарії, Греції та інших напрямків — ціна від, готелі 3★+, найближчі дати заїзду.',
};

// SSR з 5-хв ревалідацією — баланс свіжість/CDN-кеш (як на /deals).
export const revalidate = 300;

export default async function CheapPage() {
  let groups: ReturnType<typeof groupByCountry> = [];
  let error: string | null = null;
  try {
    const tours = await fetchCheapestTours({ per_country: 3, min_stars: 3 }, { revalidate: 300 });
    groups = groupByCountry(tours);
  } catch (e) {
    error = userMessageForApiError(e);
  }

  return (
    <Container className="space-y-8 py-8">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Найдешевші тури</h1>
        <p className="mt-1 text-sm text-slate-500">
          Абсолютно найнижчі ціни по кожному напрямку — чесна «ціна від», готелі від 3★, найближчі
          дати заїзду.
        </p>
      </div>

      {error ? (
        <div className="rounded-xl bg-white p-10 text-center text-sm text-danger-600 ring-1 ring-slate-200">
          Не вдалося завантажити дані: {error}
        </div>
      ) : groups.length === 0 ? (
        <div className="rounded-xl bg-white p-10 text-center text-sm text-slate-500 ring-1 ring-slate-200">
          Поки що немає доступних турів. Зазирніть трохи згодом.
        </div>
      ) : (
        <div className="space-y-10">
          {groups.map((group) => (
            <section key={group.country_iso2}>
              <h2 className="mb-4 text-lg font-semibold text-slate-900">{group.country_name}</h2>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {group.tours.map((tour) => (
                  <CheapestTourCard key={tour.hotel_id} tour={tour} />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </Container>
  );
}

import type { Metadata } from 'next';
import { Container } from '@/components/layout/Container';
import { DealsFeed } from './DealsFeed';
import { fetchDeals, userMessageForApiError } from '@/lib/api-client';

export const metadata: Metadata = {
  title: 'Гарячі знижки на тури',
  description:
    'Знижки на тури до Туреччини, Єгипту, ОАЕ, Греції та інших напрямків — аномально дешеві дати, спецціни операторів.',
};

// SSR з 5-хв ревалідацією — баланс свіжість/CDN-кеш.
export const revalidate = 300;

type DealsSearchParams = {
  country?: string;
  [key: string]: string | undefined;
};

export default async function DealsPage({
  searchParams,
}: {
  searchParams: Promise<DealsSearchParams>;
}) {
  const sp = await searchParams;
  const country = sp.country?.toUpperCase();
  let initial;
  let error: string | null = null;
  try {
    initial = await fetchDeals({ limit: 50, country }, { revalidate: 300 });
  } catch (e) {
    error = userMessageForApiError(e);
    initial = { items: [], total: 0, limit: 50, offset: 0 };
  }

  return (
    <Container className="space-y-6 py-8">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Гарячі знижки</h1>
        <p className="mt-1 text-sm text-slate-500">
          Усього виявлено {initial.total} {pluralDeals(initial.total)}.
        </p>
      </div>

      {error ? (
        <div className="rounded-xl bg-white p-10 text-center text-sm text-danger-600 ring-1 ring-slate-200">
          Не вдалося завантажити дані: {error}
        </div>
      ) : (
        <DealsFeed initial={initial} country={country} />
      )}
    </Container>
  );
}

function pluralDeals(n: number): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return 'знижку';
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return 'знижки';
  return 'знижок';
}

import type { Metadata } from 'next';
import Link from 'next/link';
import { Container } from '@/components/layout/Container';
import { fetchPromotions, userMessageForApiError } from '@/lib/api-client';
import { formatPrice, formatDateMedium, formatNights, formatMealPlan } from '@/lib/format';
import { Card, CardBody } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';

export const metadata: Metadata = {
  title: 'Добірки Farvater — гарячі тури',
  description: 'Operator-marked добірки з Farvater: гарячі тури, раннє бронювання, спецпропозиції.',
};

// SSR with 5-min ISR — matches /deals page convention.
export const revalidate = 300;

const BUCKET_LABELS: Record<string, string> = {
  'gorjashhie-tury': 'Гарячий тур',
  'rannee-bronirovanie': 'Раннє бронювання',
  'akcionnye-tury': 'Акційна добірка',
};

function bucketLabel(slug: string): string {
  return BUCKET_LABELS[slug] ?? slug;
}

type PromotionsSearchParams = {
  offset?: string;
  [key: string]: string | undefined;
};

const PAGE_SIZE = 50;

function toOffset(raw: string | undefined): number {
  const value = Number(raw);
  return Number.isFinite(value) && value > 0 ? Math.floor(value) : 0;
}

export default async function PromotionsPage({
  searchParams,
}: {
  searchParams: Promise<PromotionsSearchParams>;
}) {
  const sp = await searchParams;
  const offset = toOffset(sp.offset);
  let initial;
  let error: string | null = null;
  try {
    initial = await fetchPromotions({ limit: PAGE_SIZE, offset }, { revalidate: 300 });
  } catch (e) {
    error = userMessageForApiError(e);
    initial = { items: [], total: 0, limit: PAGE_SIZE, offset };
  }
  const nextOffset = offset + initial.items.length;
  const hasNext = nextOffset < initial.total;
  const prevOffset = Math.max(0, offset - PAGE_SIZE);

  return (
    <Container className="space-y-6 py-8">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Добірки Farvater</h1>
        {!error && (
          <p className="mt-1 text-sm text-slate-500">
            {initial.total > 0
              ? `Зараз активних пропозицій у добірках: ${initial.total}`
              : 'Зараз активних добірок немає — заходьте пізніше.'}
          </p>
        )}
      </div>

      {error ? (
        <div className="rounded-xl bg-white p-10 text-center text-sm text-danger-600 ring-1 ring-slate-200">
          {error}
        </div>
      ) : initial.items.length === 0 ? (
        <div className="rounded-xl bg-white p-10 text-center text-sm text-slate-500 ring-1 ring-slate-200">
          Поки що порожньо.
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {initial.items.map((promo) => {
              const heading = promo.hotel_name_uk;
              const href = `/hotels/${promo.hotel_slug}`;
              const starsStr = promo.hotel_stars ? '★'.repeat(promo.hotel_stars) : '';
              return (
                <Card
                  key={promo.id}
                  className="flex h-full flex-col overflow-hidden transition-shadow hover:shadow-md"
                >
                  {promo.hotel_photo_url && (
                    <Link href={href} aria-label={heading}>
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={promo.hotel_photo_url}
                        alt={heading}
                        className="h-40 w-full object-cover"
                        loading="lazy"
                      />
                    </Link>
                  )}
                  <CardBody className="flex flex-1 flex-col gap-3">
                    <div className="flex items-start justify-between gap-2">
                      <Badge variant="accent" size="md">
                        {bucketLabel(promo.bucket_slug)}
                      </Badge>
                      {promo.has_real_discount && promo.discount_pct > 0 && (
                        <span className="text-xs font-semibold text-accent-600">
                          -{Math.round(promo.discount_pct)}%
                        </span>
                      )}
                    </div>
                    <div className="space-y-0.5">
                      <Link
                        href={href}
                        className="text-base font-semibold leading-tight hover:underline"
                      >
                        {heading}
                      </Link>
                      {(starsStr || promo.destination_name) && (
                        <p className="text-xs text-slate-500">
                          {starsStr && <span>{starsStr}</span>}
                          {starsStr && promo.destination_name && <span> · </span>}
                          {promo.destination_name && <span>{promo.destination_name}</span>}
                        </p>
                      )}
                    </div>
                    <p className="text-sm text-slate-600">
                      {formatDateMedium(promo.check_in)} · {formatNights(promo.nights)} ·{' '}
                      {formatMealPlan(promo.meal_plan)}
                    </p>
                    <div className="mt-auto flex items-end justify-between gap-3">
                      <div>
                        {promo.has_real_discount && promo.red_price_uah && (
                          <div className="text-xs text-slate-400 line-through">
                            {formatPrice(promo.red_price_uah)}
                          </div>
                        )}
                        <div className="text-lg font-bold text-slate-900">
                          {formatPrice(promo.price_uah)}
                        </div>
                        <div className="mt-1 text-[11px] text-slate-500">Партнерське посилання</div>
                      </div>
                      <a
                        href={promo.deep_link}
                        target="_blank"
                        rel="nofollow sponsored noopener"
                        className="shrink-0 rounded-full bg-accent-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-accent-700"
                      >
                        На сайт оператора
                      </a>
                    </div>
                    {promo.operator_name && (
                      <p className="text-xs text-slate-500">від {promo.operator_name}</p>
                    )}
                  </CardBody>
                </Card>
              );
            })}
          </div>
          {(offset > 0 || hasNext) && (
            <nav className="flex justify-center gap-3" aria-label="Навігація добірками">
              {offset > 0 && (
                <Link
                  href={prevOffset > 0 ? `/promotions?offset=${prevOffset}` : '/promotions'}
                  className="rounded-lg bg-white px-4 py-2 text-sm font-medium text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50"
                >
                  Назад
                </Link>
              )}
              {hasNext && (
                <Link
                  href={`/promotions?offset=${nextOffset}`}
                  className="rounded-lg bg-white px-4 py-2 text-sm font-medium text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50"
                >
                  Показати більше
                </Link>
              )}
            </nav>
          )}
        </>
      )}
    </Container>
  );
}

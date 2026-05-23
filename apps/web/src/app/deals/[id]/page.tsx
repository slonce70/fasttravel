import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { Container } from '@/components/layout/Container';
import { DealCard } from '@/components/DealCard';
import { fetchDealById } from '@/lib/api-client';
import { formatPrice, formatDateLong, formatNights, formatMealPlan } from '@/lib/format';

/**
 * Deal permalink. Backend has no `/api/deals/{id}` endpoint on MVP — we paginate
 * the list and filter client-side (see lib/api-client.fetchDealById). This is
 * acceptable while we expect low-hundred deals/day.
 *
 * Backend follow-up: add `GET /api/deals/{id}` for proper indexable URLs and
 * include `hotel_slug` / `hotel_name` in `DealOut` so we don't ship "Готель #42".
 */

// Short revalidate — deals can be marked as posted/expired upstream.
export const revalidate = 60;

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  const deal = await fetchDealById(Number(id));
  if (!deal) return { title: 'Знижка не знайдена' };
  return {
    title: `Знижка -${Math.round(deal.discount_pct)}% на тур від ${formatPrice(deal.price_uah)}`,
    description: `Готель #${deal.hotel_id}, заїзд ${formatDateLong(deal.check_in)}, ${formatNights(deal.nights)}, ${formatMealPlan(deal.meal_plan)}.`,
  };
}

export default async function DealPermalinkPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const numericId = Number(id);
  if (!Number.isFinite(numericId)) notFound();

  const deal = await fetchDealById(numericId);
  if (!deal) notFound();

  return (
    <Container className="max-w-2xl space-y-4 py-8">
      <Link href="/deals" className="text-sm text-slate-500 hover:text-slate-700">
        ← Усі знижки
      </Link>
      <DealCard deal={deal} />
      <p className="text-xs text-slate-400">
        Permalink на цю знижку — посилання активне доти, доки оператор тримає
        ціну. Якщо при кліку «Купити» ви бачите іншу ціну — найімовірніше тур уже
        викупили.
      </p>
    </Container>
  );
}

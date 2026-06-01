import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { Container } from '@/components/layout/Container';
import { DealCard } from '@/components/DealCard';
import { fetchDealById } from '@/lib/api-client';
import { formatPrice, formatDateLong, formatNights, formatMealPlan } from '@/lib/format';

// Short revalidate — deals can be marked as posted/expired upstream.
export const revalidate = 60;

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  const numericId = Number(id);
  if (!Number.isFinite(numericId)) return { title: 'Пропозиція не знайдена' };
  const deal = await fetchDealById(numericId);
  if (!deal) return { title: 'Пропозиція не знайдена' };
  return {
    title: `Ціна нижча на ${Math.round(deal.discount_pct)}%: ${deal.hotel_name_uk}`,
    description: `${deal.hotel_name_uk}, ${deal.destination_name ?? 'тур'}, заїзд ${formatDateLong(deal.check_in)}, ${formatNights(deal.nights)}, ${formatMealPlan(deal.meal_plan)}, ${formatPrice(deal.price_uah)}.`,
  };
}

export default async function DealPermalinkPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const numericId = Number(id);
  if (!Number.isFinite(numericId)) notFound();

  const deal = await fetchDealById(numericId);
  if (!deal) notFound();

  return (
    <Container className="max-w-2xl space-y-4 py-8">
      <Link href="/deals" className="text-sm text-slate-500 hover:text-slate-700">
        ← Усі пропозиції
      </Link>
      <DealCard deal={deal} />
      <p className="text-xs text-slate-500">
        Permalink на цю пропозицію активний доти, доки оператор тримає ціну. Якщо при кліку «Купити»
        ви бачите іншу ціну — найімовірніше тур уже змінився або його викупили.
      </p>
    </Container>
  );
}

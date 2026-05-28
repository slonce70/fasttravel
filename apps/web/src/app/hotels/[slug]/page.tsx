import { cache } from 'react';
import type { Metadata } from 'next';
import { notFound, permanentRedirect } from 'next/navigation';
import { Container } from '@/components/layout/Container';
import { HotelPhotoCarousel } from '@/components/HotelPhotoCarousel';
import { TelegramCta } from '@/components/TelegramCta';
import { Stars } from '@/components/ui/Stars';
import { Badge } from '@/components/ui/Badge';
import { fetchHotel } from '@/lib/api-client';
import { HotelView } from './HotelView';

// ISR — hotel content changes rarely; calendar data is fetched client-side
// via TanStack Query so it stays fresh independently of the page cache.
export const revalidate = 3600;

// Per-request memoised hotel lookup: generateMetadata and the page component
// render in the same request, so this collapses them to a single backend call
// (which is itself ISR-cached for an hour via fetchHotel's default).
const getHotel = cache((slug: string) => fetchHotel(slug));

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const hotel = await getHotel(slug);
  if (!hotel) return { title: 'Готель не знайдено' };
  return {
    title: `${hotel.name_uk} — календар цін на тур`,
    description:
      hotel.description_uk?.slice(0, 160) ??
      `Календар цін на тур у ${hotel.name_uk}. Дивіться як змінюється ціна по днях і знаходьте знижки.`,
    alternates: {
      canonical: `/hotels/${hotel.canonical_slug}`,
    },
  };
}

export default async function HotelPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const hotel = await getHotel(slug);
  if (!hotel) notFound();
  if (slug !== hotel.canonical_slug) permanentRedirect(`/hotels/${hotel.canonical_slug}`);

  return (
    <Container className="space-y-6 py-6">
      <HotelPhotoCarousel photos={hotel.photos_jsonb} alt={`Фото готелю ${hotel.name_uk}`} />

      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-bold text-slate-900 sm:text-3xl">{hotel.name_uk}</h1>
          <Stars count={hotel.stars} />
        </div>
        <div className="flex flex-wrap items-center gap-3 text-sm text-slate-500">
          {hotel.review_score != null && (
            <Badge variant="success" size="md">
              {hotel.review_score.toFixed(1)} / 10
              {hotel.review_count > 0 && (
                <span className="ml-1 font-normal opacity-75">· {hotel.review_count} відгуків</span>
              )}
            </Badge>
          )}
          {hotel.name_en && <span className="text-xs text-slate-400">{hotel.name_en}</span>}
        </div>
      </header>

      {hotel.description_uk && (
        <p className="max-w-3xl text-sm leading-relaxed text-slate-600">{hotel.description_uk}</p>
      )}

      <HotelView hotel={hotel} />

      {hotel.amenities && hotel.amenities.length > 0 && (
        <section aria-labelledby="amenities-heading">
          <h2 id="amenities-heading" className="mb-3 text-lg font-semibold text-slate-800">
            Зручності
          </h2>
          <ul className="flex flex-wrap gap-2">
            {hotel.amenities.map((a) => (
              <li key={a}>
                <Badge variant="neutral" size="md">
                  {a}
                </Badge>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Most SEO traffic lands here without seeing the homepage Telegram
          CTA — surface it on every hotel page so we don't lose the funnel. */}
      <TelegramCta />
    </Container>
  );
}

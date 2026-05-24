import Link from 'next/link';
import type { Deal } from '@/lib/types';
import { Card, CardBody, CardFooter } from './ui/Card';
import { Badge } from './ui/Badge';
import { formatPrice, formatDateMedium, formatNights, formatMealPlan } from '@/lib/format';

export interface DealCardProps {
  deal: Deal;
  /**
   * Legacy override (pre backend-fixes) — kept so existing callers compile.
   * When the deal carries hotel_slug from DealOut we link to that directly.
   */
  hotelHref?: string;
  hotelName?: string;
}

export function DealCard({ deal, hotelHref, hotelName }: DealCardProps) {
  const heading = hotelName ?? deal.hotel_name_uk ?? `Готель #${deal.hotel_id}`;
  const href = hotelHref ?? (deal.hotel_slug ? `/hotels/${deal.hotel_slug}` : undefined);
  const starsStr = deal.hotel_stars ? '★'.repeat(deal.hotel_stars) : '';
  return (
    <Card className="flex h-full flex-col overflow-hidden transition-shadow hover:shadow-md">
      {deal.hotel_photo_url && (
        <Link href={href ?? `/deals/${deal.id}`} aria-label={heading}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={deal.hotel_photo_url}
            alt={heading}
            className="h-40 w-full object-cover"
            loading="lazy"
          />
        </Link>
      )}
      <CardBody className="flex flex-1 flex-col gap-3">
        <div className="flex items-start justify-between gap-2">
          <Badge variant="accent" size="md">
            🔥 -{Math.round(deal.discount_pct)}%
          </Badge>
          <span className="text-xs text-slate-400">
            {formatDateMedium(deal.detected_at)}
          </span>
        </div>
        <div className="space-y-0.5">
          {href ? (
            <Link href={href} className="text-base font-semibold leading-tight hover:underline">
              {heading}
            </Link>
          ) : (
            <span className="text-base font-semibold leading-tight">{heading}</span>
          )}
          {(starsStr || deal.destination_name) && (
            <p className="text-xs text-slate-500">
              {starsStr && <span className="text-accent-500">{starsStr}</span>}
              {starsStr && deal.destination_name && ' · '}
              {deal.destination_name && <span>{deal.destination_name}</span>}
            </p>
          )}
        </div>
        <ul className="space-y-1 text-sm text-slate-600">
          <li>📅 заїзд {formatDateMedium(deal.check_in)} · {formatNights(deal.nights)}</li>
          <li>🍽 {formatMealPlan(deal.meal_plan)}</li>
        </ul>
        <div className="mt-auto">
          <p className="text-xs text-slate-400 line-through">
            зазвичай {formatPrice(deal.baseline_p50)}
          </p>
          <p className="text-2xl font-bold text-brand-800">
            {formatPrice(deal.price_uah)}
          </p>
        </div>
      </CardBody>
      <CardFooter className="flex items-center justify-between">
        <Link
          href={`/deals/${deal.id}`}
          className="text-xs text-slate-500 hover:text-slate-700"
        >
          Permalink →
        </Link>
        {deal.deep_link && (
          <div className="flex flex-col items-end gap-0.5">
            <a
              href={deal.deep_link}
              target="_blank"
              rel="nofollow sponsored noopener"
              className="inline-flex h-9 items-center justify-center rounded-lg bg-accent-500 px-4 text-sm font-semibold text-white transition-colors hover:bg-accent-600"
            >
              Купити →
            </a>
            {/* Ukrainian Advertising Law + Google guidance — affiliate /
                sponsored links must be marked visibly, not only via
                rel="sponsored" (which is invisible to users). */}
            <span className="text-[10px] uppercase tracking-wider text-slate-400">
              Спонсорське посилання
            </span>
          </div>
        )}
      </CardFooter>
    </Card>
  );
}

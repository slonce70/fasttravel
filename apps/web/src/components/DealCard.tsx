import Link from 'next/link';
import type { Deal } from '@/lib/types';
import { Card, CardBody, CardFooter } from './ui/Card';
import { Badge } from './ui/Badge';
import { formatPrice, formatDateMedium, formatNights, formatMealPlan } from '@/lib/format';
import { getDealSignalCopy } from '@/lib/deal-signal';
import { cn } from '@/lib/utils';

export interface DealCardProps {
  deal: Deal;
}

export function DealCard({ deal }: DealCardProps) {
  const heading = deal.hotel_name_uk;
  const href = `/hotels/${deal.hotel_slug}`;
  const starsStr = deal.hotel_stars ? '★'.repeat(deal.hotel_stars) : '';
  const signal = getDealSignalCopy(deal.detection_method);
  return (
    <Card className="flex h-full flex-col overflow-hidden transition-shadow hover:shadow-md">
      <Link
        href={href}
        aria-label={heading}
        className="relative block h-40 w-full overflow-hidden bg-slate-100"
      >
        {deal.hotel_photo_url ? (
          /* eslint-disable-next-line @next/next/no-img-element */
          <img
            src={deal.hotel_photo_url}
            alt={heading}
            className="h-full w-full object-cover"
            loading="lazy"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-3xl text-slate-300">
            🏨
          </div>
        )}
      </Link>
      <CardBody className="flex flex-1 flex-col gap-3">
        <div className="flex items-start justify-between gap-2">
          <Badge variant={signal.badgeVariant} size="md">
            {signal.badgeIcon} -{Math.round(deal.discount_pct)}%
          </Badge>
          <span className="text-xs text-slate-400">{formatDateMedium(deal.detected_at)}</span>
        </div>
        <div className="space-y-0.5">
          <Link href={href} className="text-base font-semibold leading-tight hover:underline">
            {heading}
          </Link>
          {(starsStr || deal.destination_name) && (
            <p className="text-xs text-slate-500">
              {starsStr && <span className="text-accent-500">{starsStr}</span>}
              {starsStr && deal.destination_name && ' · '}
              {deal.destination_name && <span>{deal.destination_name}</span>}
            </p>
          )}
        </div>
        <ul className="space-y-1 text-sm text-slate-600">
          <li>
            📅 заїзд {formatDateMedium(deal.check_in)} · {formatNights(deal.nights)}
          </li>
          <li>🍽 {formatMealPlan(deal.meal_plan)}</li>
        </ul>
        <p className="rounded-md bg-slate-50 px-2.5 py-2 text-xs leading-snug text-slate-600">
          {signal.reason}
        </p>
        <div className="mt-auto">
          <p className={cn('text-xs text-slate-400', signal.strikeBaseline && 'line-through')}>
            {signal.baselineLabel} {formatPrice(deal.baseline_p50)}
          </p>
          <p className="text-2xl font-bold text-brand-800">{formatPrice(deal.price_uah)}</p>
        </div>
      </CardBody>
      <CardFooter className="flex items-center justify-between">
        <Link
          href={`/deals/${deal.id}`}
          className="text-xs text-slate-500 hover:text-slate-700"
          aria-label={`Постійне посилання на варіант ${heading}`}
        >
          Permalink →
        </Link>
        {deal.deep_link && (
          <div className="flex flex-col items-end gap-0.5">
            <a
              href={deal.deep_link}
              target="_blank"
              rel="nofollow sponsored noopener"
              aria-label={`Купити тур у ${heading} на сайті оператора (зовнішнє посилання)`}
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

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
    <Card className="group flex h-full flex-col overflow-hidden rounded-xl shadow-[0_18px_45px_-28px_rgba(15,23,42,0.55)] transition-all hover:-translate-y-0.5 hover:shadow-[0_24px_60px_-32px_rgba(15,23,42,0.65)]">
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
            className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
            loading="lazy"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-slate-100 to-teal-50 text-slate-300">
            <svg
              aria-hidden="true"
              viewBox="0 0 32 32"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.5}
              strokeLinecap="round"
              strokeLinejoin="round"
              className="h-12 w-12"
            >
              <path d="M5 27h22" />
              <path d="M8 27V8.5A1.5 1.5 0 0 1 9.5 7h8A1.5 1.5 0 0 1 19 8.5V27" />
              <path d="M19 14h4.5A1.5 1.5 0 0 1 25 15.5V27" />
              <path d="M11.5 12h3M11.5 17h3M11.5 22h3" />
            </svg>
          </div>
        )}
      </Link>
      <CardBody className="flex flex-1 flex-col gap-3">
        <div className="flex items-start justify-between gap-2">
          <Badge variant={signal.badgeVariant} size="md" className="rounded-md">
            {signal.badgeIcon} -{Math.round(deal.discount_pct)}%
          </Badge>
          <span className="text-xs text-slate-500">{formatDateMedium(deal.detected_at)}</span>
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
            <span className="font-medium text-slate-800">Заїзд</span>{' '}
            {formatDateMedium(deal.check_in)} · {formatNights(deal.nights)}
          </li>
          <li>
            <span className="font-medium text-slate-800">Харчування</span>{' '}
            {formatMealPlan(deal.meal_plan)}
          </li>
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
          className="inline-flex min-h-11 items-center text-xs font-medium text-slate-500 hover:text-slate-700"
          aria-label={`Деталі пропозиції ${heading}`}
        >
          Деталі пропозиції →
        </Link>
        {deal.deep_link && (
          <div className="flex flex-col items-end gap-0.5">
            <a
              href={deal.deep_link}
              target="_blank"
              rel="nofollow sponsored noopener"
              aria-label={`Купити тур у ${heading} на сайті оператора (зовнішнє посилання)`}
              className="inline-flex h-11 items-center justify-center rounded-lg bg-accent-600 px-4 text-sm font-semibold text-white transition-colors hover:bg-accent-700"
            >
              Купити →
            </a>
            {/* Ukrainian Advertising Law + Google guidance — affiliate /
                sponsored links must be marked visibly, not only via
                rel="sponsored" (which is invisible to users). */}
            <span className="text-[10px] uppercase tracking-wider text-slate-500">
              Спонсорське посилання
            </span>
          </div>
        )}
      </CardFooter>
    </Card>
  );
}

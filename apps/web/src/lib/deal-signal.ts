import type { Deal } from './types';

export type DealSignalCopy = {
  badgeIcon: string;
  badgeVariant: 'neutral' | 'success' | 'accent' | 'danger' | 'brand';
  reason: string;
  baselineLabel: string;
  strikeBaseline: boolean;
};

export function getDealSignalCopy(method: Deal['detection_method']): DealSignalCopy {
  switch ((method || 'percentile').toLowerCase()) {
    case 'calendar_anomaly':
      return {
        badgeIcon: '📉',
        badgeVariant: 'success',
        reason: 'Аномально дешева дата у цьому готелі',
        baselineLabel: 'інші дати',
        strikeBaseline: true,
      };
    case 'promo_discount':
      return {
        badgeIcon: '🏷',
        badgeVariant: 'accent',
        reason: 'Спецціна оператора',
        baselineLabel: 'ціна оператора до акції',
        strikeBaseline: true,
      };
    case 'peer_anomaly':
      return {
        badgeIcon: '📊',
        badgeVariant: 'neutral',
        reason: 'Дешевше за схожі готелі',
        baselineLabel: 'орієнтир схожих',
        strikeBaseline: false,
      };
    default:
      return {
        badgeIcon: '📊',
        badgeVariant: 'brand',
        reason: 'Нижче історичної ціни цього готелю',
        baselineLabel: 'зазвичай',
        strikeBaseline: true,
      };
  }
}

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
        reason: 'Ця дата значно дешевша за сусідні у цьому готелі',
        baselineLabel: 'інші дати',
        strikeBaseline: true,
      };
    case 'promo_discount':
      return {
        badgeIcon: '🏷',
        badgeVariant: 'accent',
        reason: 'Спецціна від оператора — обмежена пропозиція',
        baselineLabel: 'ціна оператора до акції',
        strikeBaseline: true,
      };
    case 'peer_anomaly':
      return {
        badgeIcon: '📊',
        badgeVariant: 'neutral',
        reason: 'Дешевше за аналогічні готелі в цьому регіоні',
        baselineLabel: 'орієнтир схожих',
        strikeBaseline: false,
      };
    default:
      return {
        badgeIcon: '📊',
        badgeVariant: 'brand',
        reason: 'Ціна нижча за звичайну для цього готелю',
        baselineLabel: 'зазвичай',
        strikeBaseline: true,
      };
  }
}

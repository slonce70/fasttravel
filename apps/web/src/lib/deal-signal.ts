import type { Deal } from './types';

export type DealSignalCopy = {
  badgeIcon: string;
  badgeVariant: 'neutral' | 'success' | 'accent' | 'danger' | 'brand';
  reason: string;
  baselineLabel: string;
  strikeBaseline: boolean;
};

export function getDealSignalCopy(method: Deal['detection_method']): DealSignalCopy {
  switch ((method || '').trim().toLowerCase()) {
    case 'calendar_anomaly':
      return {
        badgeIcon: 'Дата',
        badgeVariant: 'success',
        reason: 'Ця дата значно дешевша за сусідні у цьому готелі',
        baselineLabel: 'інші дати',
        strikeBaseline: false,
      };
    case 'promo_discount':
      return {
        badgeIcon: 'Акція',
        badgeVariant: 'accent',
        reason: 'Спецціна від оператора — обмежена пропозиція',
        baselineLabel: 'ціна оператора до акції',
        strikeBaseline: true,
      };
    case 'peer_anomaly':
      return {
        badgeIcon: 'Регіон',
        badgeVariant: 'neutral',
        reason: 'Дешевше за схожі готелі в цьому регіоні',
        baselineLabel: 'орієнтир схожих',
        strikeBaseline: false,
      };
    case 'percentile':
      return {
        badgeIcon: 'Історія',
        badgeVariant: 'brand',
        reason: 'Ціна нижча за звичайну для цього готелю',
        baselineLabel: 'зазвичай',
        strikeBaseline: false,
      };
    case '':
    default:
      if (method && method.trim()) {
        return {
          badgeIcon: 'Орієнтир',
          badgeVariant: 'neutral',
          reason: 'Порівняльний орієнтир ціни',
          baselineLabel: 'орієнтир',
          strikeBaseline: false,
        };
      }
      return {
        badgeIcon: 'Історія',
        badgeVariant: 'brand',
        reason: 'Ціна нижча за звичайну для цього готелю',
        baselineLabel: 'зазвичай',
        strikeBaseline: false,
      };
  }
}

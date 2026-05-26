import Link from 'next/link';
import { Container } from '@/components/layout/Container';

export default function NotFound() {
  return (
    <Container className="py-20 text-center">
      <p className="text-sm font-medium text-brand-700">404</p>
      <h1 className="mt-2 text-3xl font-bold text-slate-900">Сторінку не знайдено</h1>
      <p className="mt-3 text-slate-600">Можливо, готель був видалений або URL змінився.</p>
      <Link
        href="/"
        className="mt-6 inline-flex h-11 items-center justify-center rounded-lg bg-brand-700 px-6 text-sm font-medium text-white hover:bg-brand-800"
      >
        На головну
      </Link>
    </Container>
  );
}

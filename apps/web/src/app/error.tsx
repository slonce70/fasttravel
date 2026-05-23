'use client';

import { useEffect } from 'react';
import { Container } from '@/components/layout/Container';

export default function ErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // TODO: integrate Sentry browser SDK (Phase 2).
    // eslint-disable-next-line no-console
    console.error('App error:', error);
  }, [error]);

  return (
    <Container className="py-20 text-center">
      <h1 className="text-2xl font-bold text-slate-900">Щось пішло не так</h1>
      <p className="mt-3 text-slate-600">
        Ми вже знаємо про помилку. Спробуйте ще раз через декілька секунд.
      </p>
      {error.digest && (
        <p className="mt-2 text-xs text-slate-400">код: {error.digest}</p>
      )}
      <button
        type="button"
        onClick={reset}
        className="mt-6 inline-flex h-11 items-center justify-center rounded-lg bg-brand-700 px-6 text-sm font-medium text-white hover:bg-brand-800"
      >
        Спробувати ще раз
      </button>
    </Container>
  );
}

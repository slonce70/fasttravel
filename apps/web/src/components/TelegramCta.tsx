import Link from 'next/link';

/** Telegram channel CTA — used on home and various landing pages. */
export function TelegramCta() {
  return (
    <section
      aria-labelledby="tg-cta-heading"
      className="rounded-2xl bg-gradient-to-br from-brand-700 to-brand-900 p-6 text-white sm:p-10"
    >
      <div className="grid items-center gap-6 md:grid-cols-[1fr_auto]">
        <div>
          <h2 id="tg-cta-heading" className="text-xl font-bold sm:text-2xl">
            Гарячі знижки приходять у Telegram
          </h2>
          <p className="mt-2 text-sm text-brand-100 sm:text-base">
            Щодня — до 30 знижок на тури до Туреччини, Єгипту, ОАЕ, Греції та інших напрямків. Без
            спаму, лише найкращі пропозиції.
          </p>
        </div>
        <Link
          href="/telegram"
          className="inline-flex h-12 items-center justify-center rounded-lg bg-white px-6 text-sm font-semibold text-brand-800 transition-colors hover:bg-slate-100"
        >
          Підписатись →
        </Link>
      </div>
    </section>
  );
}

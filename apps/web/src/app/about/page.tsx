import type { Metadata } from 'next';
import { Container } from '@/components/layout/Container';

export const metadata: Metadata = {
  title: 'Про FastTravel',
  description:
    'FastTravel — інформаційний агрегатор турів. Ми не туроператор, не агент, не продавець: ми показуємо ціни, ви купуєте напряму.',
};

export default function AboutPage() {
  return (
    <Container className="max-w-3xl space-y-6 py-10 text-slate-700">
      <h1 className="text-3xl font-bold text-slate-900">Про FastTravel</h1>

      <p>
        FastTravel — український <strong>інформаційний агрегатор</strong> турів. Ми збираємо
        публічно доступні ціни на тури у популярні напрямки у єдиному календарі і показуємо їх
        безкоштовно.
      </p>

      <section>
        <h2 className="mb-2 text-xl font-semibold text-slate-900">Що ми робимо</h2>
        <ul className="list-inside list-disc space-y-1">
          <li>Збираємо актуальні ціни з доступних операторських і агрегаторних джерел.</li>
          <li>Будуємо календар цін на 90 днів вперед для кожного готелю.</li>
          <li>Виявляємо аномально низькі ціни і постимо в Telegram-канал.</li>
          <li>Ведемо рейтинги готелів за відгуками користувачів.</li>
        </ul>
      </section>

      <section>
        <h2 className="mb-2 text-xl font-semibold text-slate-900">Чого ми НЕ робимо</h2>
        <ul className="list-inside list-disc space-y-1">
          <li>
            <strong>Ми не туроператор</strong> і не маємо ліцензії на турдіяльність — її і не
            потребуємо, бо не продаємо тури.
          </li>
          <li>Не приймаємо платежі. Усі покупки відбуваються на сайтах операторів.</li>
          <li>Не зберігаємо персональні дані про користувачів окрім cookie-аналітики.</li>
          <li>Не маніпулюємо рейтингами. Список знижок ранжуємо за алгоритмом.</li>
        </ul>
      </section>

      <section>
        <h2 className="mb-2 text-xl font-semibold text-slate-900">Джерела даних</h2>
        <p>
          На цьому етапі каталог і ціни формуються з доступного операторського контенту, зокрема
          Farvater-derived pipeline, та нормалізуються в єдиний календар. Ми не заявляємо
          ексклюзивних або офіційних партнерств там, де вони ще не оформлені. Якщо ви туроператор і
          хочете бути у нашому каталозі — напишіть на{' '}
          <a href="mailto:partners@fasttravel.com.ua" className="text-brand-700 hover:underline">
            partners@fasttravel.com.ua
          </a>
          .
        </p>
      </section>

      <section>
        <h2 className="mb-2 text-xl font-semibold text-slate-900">Контакти</h2>
        <p>
          Загальні питання:{' '}
          <a href="mailto:hello@fasttravel.com.ua" className="text-brand-700 hover:underline">
            hello@fasttravel.com.ua
          </a>
        </p>
      </section>

      <p className="border-l-4 border-slate-200 pl-4 text-sm text-slate-500">
        Дисклеймер: ціни на сайті можуть відрізнятись від актуальних на сайті оператора через
        затримку оновлення (до 12 годин). Завжди перевіряйте фінальну вартість на стороні
        туроператора перед оплатою.
      </p>
    </Container>
  );
}

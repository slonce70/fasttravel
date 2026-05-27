import type { Metadata } from 'next';
import { Container } from '@/components/layout/Container';
import { Card, CardBody } from '@/components/ui/Card';
import { TELEGRAM_CHANNEL_URL } from '@/lib/site-config';

export const metadata: Metadata = {
  title: 'Telegram-канал з гарячими знижками',
  description:
    'Підпишіться на Telegram-канал FastTravel — до 30 знижок на тури до Туреччини, Єгипту, ОАЕ, Греції щодня.',
};

const TG_CHANNEL = TELEGRAM_CHANNEL_URL;
const TG_QR_URL = `https://api.qrserver.com/v1/create-qr-code/?size=240x240&data=${encodeURIComponent(TG_CHANNEL)}`;

export default function TelegramPage() {
  return (
    <Container className="max-w-3xl space-y-8 py-10">
      <header className="text-center">
        <h1 className="text-3xl font-bold text-slate-900">Гарячі знижки в Telegram</h1>
        <p className="mt-3 text-slate-600">
          Бот FastTravel постить новини тільки тоді, коли алгоритм знайшов знижку більше ніж -15%
          від середньої історичної ціни готелю. Без спаму, до 30 постів на добу.
        </p>
      </header>

      <Card>
        <CardBody className="flex flex-col items-center gap-6 sm:flex-row sm:items-start">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={TG_QR_URL}
            alt={`QR-код на Telegram-канал ${TG_CHANNEL}`}
            width={180}
            height={180}
            className="rounded-lg border border-slate-200"
          />
          <div className="flex-1 space-y-4 text-center sm:text-left">
            <p className="text-slate-700">Скануйте QR-код або натисніть кнопку нижче.</p>
            <a
              href={TG_CHANNEL}
              target="_blank"
              rel="noopener"
              className="inline-flex h-12 items-center justify-center rounded-lg bg-brand-700 px-6 text-base font-semibold text-white transition-colors hover:bg-brand-800"
            >
              Перейти у Telegram →
            </a>
            <p className="text-xs text-slate-500">
              Канал лише з повідомленнями — без чату. Відписатись можна у будь-який момент.
            </p>
          </div>
        </CardBody>
      </Card>

      <section aria-labelledby="how-it-works">
        <h2 id="how-it-works" className="mb-3 text-xl font-bold text-slate-900">
          Як це працює
        </h2>
        <ol className="space-y-2 text-sm text-slate-600">
          <li>1. Двічі на день збираємо ціни з туроператорів по ~3000 готелях у 14 країнах.</li>
          <li>2. Будуємо профіль звичайної ціни для кожного готелю за останні 60 днів.</li>
          <li>3. Якщо ціна суттєво нижча за звичайну — постимо знижку в канал.</li>
          <li>4. Ви бачите кнопку «Купити», яка веде на сайт оператора. Купуєте напряму.</li>
        </ol>
      </section>
    </Container>
  );
}

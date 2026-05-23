import Link from 'next/link';
import { Container } from './Container';

export function Footer() {
  return (
    <footer className="mt-16 border-t border-slate-200 bg-white py-8 text-sm text-slate-500">
      <Container className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <p>
          © {new Date().getFullYear()} FastTravel — інформаційний агрегатор турів.
          <span className="ml-2 hidden text-xs sm:inline">Ми не туроператор.</span>
        </p>
        <nav aria-label="Допоміжна навігація">
          <ul className="flex flex-wrap gap-4">
            <li>
              <Link href="/about" className="hover:text-slate-700">
                Про нас
              </Link>
            </li>
            <li>
              <Link href="/telegram" className="hover:text-slate-700">
                Telegram-канал
              </Link>
            </li>
            <li>
              <a
                href="mailto:hello@fasttravel.com.ua"
                className="hover:text-slate-700"
              >
                hello@fasttravel.com.ua
              </a>
            </li>
          </ul>
        </nav>
      </Container>
    </footer>
  );
}

import Link from 'next/link';
import { Container } from './Container';

const NAV = [
  { href: '/search', label: 'Пошук турів' },
  { href: '/deals', label: 'Гарячі знижки' },
  { href: '/destinations/turkey', label: 'Туреччина' },
  { href: '/telegram', label: 'Telegram' },
  { href: '/about', label: 'Про нас' },
];

export function Header() {
  return (
    <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/90 backdrop-blur supports-[backdrop-filter]:bg-white/70">
      <Container className="flex h-14 items-center justify-between gap-6">
        <Link href="/" className="flex items-center gap-2 font-semibold text-brand-800">
          <span aria-hidden className="text-xl">✈️</span>
          <span className="text-base sm:text-lg">FastTravel</span>
          <span className="hidden text-xs font-normal text-slate-400 sm:inline">
            календар цін на тури
          </span>
        </Link>
        <nav aria-label="Головна навігація" className="hidden md:block">
          <ul className="flex items-center gap-1">
            {NAV.map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className="rounded px-3 py-2 text-sm text-slate-700 transition-colors hover:bg-slate-100 hover:text-brand-800"
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        {/* Mobile: minimalist quick-links. Hamburger comes in Phase 2. */}
        <nav aria-label="Швидкі дії" className="md:hidden">
          <Link
            href="/deals"
            className="rounded px-3 py-2 text-sm font-medium text-accent-600"
          >
            Знижки
          </Link>
        </nav>
      </Container>
    </header>
  );
}

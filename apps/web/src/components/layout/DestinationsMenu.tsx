'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import type { CountryOut } from '@/lib/types';

/**
 * Accessible "Напрямки" dropdown. A CSS-only hover menu was keyboard-
 * inaccessible: the items were `visibility:hidden`, so they could not be
 * focused and `group-focus-within` never fired. This is a small client island
 * so the rest of the Header stays a server component.
 */
export function DestinationsMenu({ countries }: { countries: CountryOut[] }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLLIElement>(null);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onClick);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onClick);
    };
  }, [open]);

  return (
    <li ref={ref} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="rounded px-3 py-2 text-sm text-slate-700 transition-colors hover:bg-slate-100 hover:text-brand-800"
      >
        Напрямки ▾
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-40 mt-1 w-56 rounded-lg border border-slate-200 bg-white p-1 shadow-lg"
        >
          {countries.map((c) => (
            <Link
              key={`${c.country_iso2}-${c.id}`}
              role="menuitem"
              href={`/destinations/${c.country_slug}`}
              onClick={() => setOpen(false)}
              className="block rounded px-3 py-2 text-sm text-slate-700 hover:bg-slate-100 hover:text-brand-800"
            >
              {c.name_uk}
              <span className="ml-2 text-xs text-slate-400">{c.hotel_count}</span>
            </Link>
          ))}
        </div>
      )}
    </li>
  );
}

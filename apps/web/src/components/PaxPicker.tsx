'use client';

import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react';

/**
 * Pax composition shared with SearchForm and search URL serialization.
 *
 *  - `adults`: 1-9 (matches farvater.travel / standard tour operator limits).
 *  - `kids`:   number[] of ages (1-17 each). Length is the kid count.
 *              Storing ages in an array (rather than {count, ages[]}) avoids
 *              two sources of truth that can disagree.
 */
export interface PaxValue {
  adults: number;
  kids: number[];
}

export const DEFAULT_PAX: PaxValue = { adults: 2, kids: [] };

/** Default kid age when user clicks +. Farvater uses 7. */
const DEFAULT_KID_AGE = 7;

const ADULT_MIN = 1;
const ADULT_MAX = 9;
const KIDS_MAX = 4;
const KID_AGE_MIN = 1;
const KID_AGE_MAX = 17;

export interface PaxPickerProps {
  value: PaxValue;
  onChange: (next: PaxValue) => void;
  /** Optional className for the outer wrapper (controls width in the form grid). */
  className?: string;
}

/**
 * Mobile-first pax/kids selector.
 *
 *  - Trigger button shows "X дорослих, Y дітей" (Ukrainian noun plural rules).
 *  - On click opens:
 *      mobile  (< md)  → bottom sheet (fixed, slide-up, full-width)
 *      desktop (≥ md)  → popover anchored to trigger
 *    Layout is pure CSS via Tailwind responsive classes — no JS viewport
 *    detection (avoids hydration mismatch).
 *  - Adults/kids counters with +/− buttons; age selects appear dynamically
 *    per child (1-17). Increment keeps existing ages, decrement trims the tail.
 *  - A11y: aria-expanded + aria-controls on trigger, role=dialog + aria-modal
 *    on popup, ESC closes, click-outside closes, focus returns to trigger.
 */
export function PaxPicker({ value, onChange, className }: PaxPickerProps) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const popoverId = useId();

  const close = useCallback(() => {
    setOpen(false);
    // Restore focus so keyboard users don't get lost.
    triggerRef.current?.focus();
  }, []);

  // ESC closes + click-outside closes. Single effect, single listener pair,
  // only attached while open to keep idle cost zero.
  useEffect(() => {
    if (!open) return;

    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault();
        close();
      }
    }
    function onDown(e: MouseEvent) {
      const target = e.target as Node;
      if (
        popoverRef.current &&
        !popoverRef.current.contains(target) &&
        triggerRef.current &&
        !triggerRef.current.contains(target)
      ) {
        setOpen(false);
      }
    }
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onDown);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onDown);
    };
  }, [open, close]);

  function setAdults(next: number) {
    const clamped = Math.max(ADULT_MIN, Math.min(ADULT_MAX, next));
    onChange({ ...value, adults: clamped });
  }

  function setKidsCount(next: number) {
    const clamped = Math.max(0, Math.min(KIDS_MAX, next));
    const current = value.kids;
    let kids: number[];
    if (clamped > current.length) {
      // Append default ages — keeps existing user-set ages intact.
      kids = [
        ...current,
        ...Array(clamped - current.length).fill(DEFAULT_KID_AGE),
      ];
    } else {
      // Trim the tail — preserves the head ages on +/- ping-pong.
      kids = current.slice(0, clamped);
    }
    onChange({ ...value, kids });
  }

  function setKidAge(index: number, age: number) {
    const kids = [...value.kids];
    kids[index] = age;
    onChange({ ...value, kids });
  }

  // First focusable inside the dialog should grab focus on open.
  const firstFocusRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (open) firstFocusRef.current?.focus();
  }, [open]);

  return (
    <div className={`relative ${className ?? ''}`}>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={popoverId}
        className="input flex items-center justify-between text-left"
      >
        <span>{paxLabel(value)}</span>
        <svg
          aria-hidden="true"
          className={`h-4 w-4 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`}
          viewBox="0 0 20 20"
          fill="currentColor"
        >
          <path
            fillRule="evenodd"
            d="M5.23 7.21a.75.75 0 011.06.02L10 11.06l3.71-3.83a.75.75 0 111.08 1.04l-4.25 4.39a.75.75 0 01-1.08 0L5.21 8.27a.75.75 0 01.02-1.06z"
            clipRule="evenodd"
          />
        </svg>
      </button>

      {open && (
        <>
          {/* Mobile backdrop — fades in beneath the sheet, lets users tap to close. */}
          <div
            aria-hidden="true"
            className="fixed inset-0 z-40 bg-slate-900/30 md:hidden"
            onClick={() => setOpen(false)}
          />
          <div
            ref={popoverRef}
            id={popoverId}
            role="dialog"
            aria-modal="true"
            aria-label="Кількість туристів"
            className={[
              // Mobile: bottom sheet
              'fixed inset-x-0 bottom-0 z-50 rounded-t-2xl bg-white p-5 shadow-2xl',
              // Desktop: popover anchored to trigger
              'md:absolute md:inset-x-auto md:bottom-auto md:left-0 md:right-auto md:top-full md:z-30 md:mt-2 md:w-80 md:rounded-xl md:p-4 md:ring-1 md:ring-slate-200',
              'animate-[fadeIn_120ms_ease-out]',
            ].join(' ')}
          >
            <div className="flex items-center justify-between md:hidden">
              <span className="text-base font-semibold text-slate-900">
                Туристи
              </span>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Закрити"
                className="-mr-2 rounded-md p-2 text-slate-500 hover:text-slate-700"
              >
                <svg className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                  <path
                    fillRule="evenodd"
                    d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z"
                    clipRule="evenodd"
                  />
                </svg>
              </button>
            </div>

            <div className="mt-3 space-y-4 md:mt-0">
              <CounterRow
                label="Дорослі"
                sublabel="від 18 років"
                value={value.adults}
                min={ADULT_MIN}
                max={ADULT_MAX}
                onDec={() => setAdults(value.adults - 1)}
                onInc={() => setAdults(value.adults + 1)}
                decRef={firstFocusRef}
              />
              <CounterRow
                label="Діти"
                sublabel="до 17 років"
                value={value.kids.length}
                min={0}
                max={KIDS_MAX}
                onDec={() => setKidsCount(value.kids.length - 1)}
                onInc={() => setKidsCount(value.kids.length + 1)}
              />

              {value.kids.length > 0 && (
                <div className="space-y-2 rounded-lg bg-slate-50 p-3">
                  <span className="text-xs font-medium text-slate-600">
                    Вік дітей на дату подорожі
                  </span>
                  <div className="grid grid-cols-2 gap-2">
                    {value.kids.map((age, i) => (
                      <label
                        key={i}
                        className="flex flex-col gap-1 text-xs text-slate-600"
                      >
                        <span>Дитина {i + 1}</span>
                        <select
                          value={age}
                          onChange={(e) =>
                            setKidAge(i, Number(e.target.value))
                          }
                          aria-label={`Вік дитини ${i + 1}`}
                          className="input"
                        >
                          {Array.from(
                            { length: KID_AGE_MAX - KID_AGE_MIN + 1 },
                            (_, k) => k + KID_AGE_MIN,
                          ).map((a) => (
                            <option key={a} value={a}>
                              {a} {ageWord(a)}
                            </option>
                          ))}
                        </select>
                      </label>
                    ))}
                  </div>
                </div>
              )}

              <button
                type="button"
                onClick={close}
                className="h-10 w-full rounded-lg bg-brand-700 text-sm font-medium text-white hover:bg-brand-800 active:bg-brand-900"
              >
                Готово
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface CounterRowProps {
  label: string;
  sublabel?: string;
  value: number;
  min: number;
  max: number;
  onDec: () => void;
  onInc: () => void;
  decRef?: React.Ref<HTMLButtonElement>;
}

function CounterRow({
  label,
  sublabel,
  value,
  min,
  max,
  onDec,
  onInc,
  decRef,
}: CounterRowProps) {
  // Block + and - keypresses from submitting the parent form.
  function noSubmit(e: ReactKeyboardEvent<HTMLButtonElement>) {
    if (e.key === 'Enter') e.preventDefault();
  }
  return (
    <div className="flex items-center justify-between">
      <div className="flex flex-col">
        <span className="text-sm font-medium text-slate-900">{label}</span>
        {sublabel && (
          <span className="text-xs text-slate-500">{sublabel}</span>
        )}
      </div>
      <div className="flex items-center gap-3">
        <button
          ref={decRef}
          type="button"
          onClick={onDec}
          onKeyDown={noSubmit}
          disabled={value <= min}
          aria-label={`Зменшити ${label.toLowerCase()}`}
          className="flex h-8 w-8 items-center justify-center rounded-full ring-1 ring-slate-300 text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
        >
          −
        </button>
        <span
          className="w-5 text-center text-sm font-semibold tabular-nums"
          aria-live="polite"
        >
          {value}
        </span>
        <button
          type="button"
          onClick={onInc}
          onKeyDown={noSubmit}
          disabled={value >= max}
          aria-label={`Збільшити ${label.toLowerCase()}`}
          className="flex h-8 w-8 items-center justify-center rounded-full ring-1 ring-slate-300 text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
        >
          +
        </button>
      </div>
    </div>
  );
}

/** Ukrainian plural for "adults" + "kids". */
export function paxLabel({ adults, kids }: PaxValue): string {
  const a = `${adults} ${pluralUk(adults, ['дорослий', 'дорослих', 'дорослих'])}`;
  const k = `${kids.length} ${pluralUk(kids.length, ['дитина', 'дитини', 'дітей'])}`;
  return `${a}, ${k}`;
}

function ageWord(n: number): string {
  return pluralUk(n, ['рік', 'роки', 'років']);
}

function pluralUk(n: number, forms: [string, string, string]): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return forms[0];
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return forms[1];
  return forms[2];
}

// ---------------------------------------------------------------------------
// URL helpers — keep encode/decode next to the type so they stay in lock-step.
// ---------------------------------------------------------------------------

/** Reads adults + kids from a URLSearchParams-like getter. */
export function paxFromSearchParams(
  get: (key: string) => string | null,
): PaxValue {
  const adultsRaw = get('adults');
  const kidsRaw = get('kids');
  const adults = adultsRaw ? Number(adultsRaw) : DEFAULT_PAX.adults;
  const kids = kidsRaw
    ? kidsRaw
        .split(',')
        .map((s) => Number(s.trim()))
        .filter((n) => Number.isFinite(n) && n >= KID_AGE_MIN && n <= KID_AGE_MAX)
    : [];
  return {
    adults: Number.isFinite(adults)
      ? Math.max(ADULT_MIN, Math.min(ADULT_MAX, adults))
      : DEFAULT_PAX.adults,
    kids: kids.slice(0, KIDS_MAX),
  };
}

/** Writes adults + kids into URLSearchParams (only if non-default). */
export function paxToSearchParams(
  qs: URLSearchParams,
  value: PaxValue,
): void {
  // Always include adults so the backend knows the explicit pax — most
  // operator APIs need it. Kids only when non-empty to keep URLs clean.
  qs.set('adults', String(value.adults));
  if (value.kids.length > 0) {
    qs.set('kids', value.kids.join(','));
  }
}

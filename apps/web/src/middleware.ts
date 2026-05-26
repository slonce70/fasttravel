import { NextResponse, type NextRequest } from 'next/server';

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

type HotelSlugLookup = {
  canonical_slug?: string;
};

export async function middleware(request: NextRequest) {
  const [, section, slug] = request.nextUrl.pathname.split('/');
  if (section !== 'hotels' || !slug) {
    return NextResponse.next();
  }

  try {
    const response = await fetch(`${API_BASE}/api/hotels/${encodeURIComponent(slug)}`, {
      cache: 'no-store',
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) return NextResponse.next();

    const hotel = (await response.json()) as HotelSlugLookup;
    if (hotel.canonical_slug && hotel.canonical_slug !== slug) {
      const canonicalUrl = request.nextUrl.clone();
      canonicalUrl.pathname = `/hotels/${hotel.canonical_slug}`;
      return NextResponse.redirect(canonicalUrl, 301);
    }
  } catch {
    return NextResponse.next();
  }

  return NextResponse.next();
}

export const config = {
  matcher: '/hotels/:slug',
};

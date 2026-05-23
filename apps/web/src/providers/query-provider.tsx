'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';

/**
 * Root TanStack Query provider. Mounted in the root layout.
 *
 * Defaults chosen for our read-mostly UX:
 *   - staleTime 5 min: calendar data refreshes hourly on the backend; 5 min
 *     on the client keeps re-renders cheap while still showing fresh data.
 *   - retry 2: tolerate transient Cloudflare 5xx from the origin proxy.
 *   - refetchOnWindowFocus false: too noisy for a browse-heavy site.
 */
export function QueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 5 * 60 * 1000,
            gcTime: 30 * 60 * 1000,
            retry: 2,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

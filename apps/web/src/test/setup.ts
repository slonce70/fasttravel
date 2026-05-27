// Vitest global setup — registers @testing-library/jest-dom matchers
// (toBeInTheDocument, toHaveTextContent, etc.) and tears down RTL
// after each test so DOM doesn't leak between cases.
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

afterEach(() => {
  cleanup();
});

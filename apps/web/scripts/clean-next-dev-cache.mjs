import { rm } from 'node:fs/promises';
import { join } from 'node:path';

const cacheDir = join(process.cwd(), '.next');

try {
  await rm(cacheDir, { recursive: true, force: true });
  console.log('cleaned .next dev cache');
} catch (error) {
  console.warn(`could not clean .next dev cache: ${error.message}`);
}

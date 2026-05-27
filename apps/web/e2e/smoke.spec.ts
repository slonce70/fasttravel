import { expect, test } from '@playwright/test';

const apiBase = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
const browserErrorsByPage = new WeakMap<object, string[]>();

test.beforeAll(async ({ request }) => {
  if (process.env.WEB_E2E_BASE_URL) return;
  const health = await request.get(`${apiBase}/health`);
  expect(health.ok(), `API must be reachable at ${apiBase}/health`).toBe(true);
});

test.beforeEach(async ({ page }) => {
  const browserErrors: string[] = [];
  browserErrorsByPage.set(page, browserErrors);
  await page.addInitScript(() => {
    window.sessionStorage.setItem('ft:hotel-refresh:last-at', String(Date.now()));
  });
  page.on('console', (message) => {
    if (message.type() === 'error') browserErrors.push(message.text());
  });
  page.on('pageerror', (error) => browserErrors.push(error.message));
});

test.afterEach(async ({ page }) => {
  expect(browserErrorsByPage.get(page) ?? []).toEqual([]);
});

test('Telegram page links to the configured public channel', async ({ page }) => {
  await page.goto('/telegram');

  await expect(page).toHaveTitle(/Telegram-канал з гарячими знижками/);
  await expect(page.locator('a[href="https://t.me/testtyhhh"]')).toHaveCount(1);
});

test('search results navigate to a real hotel detail page with a price calendar', async ({
  page,
}) => {
  await page.goto('/search?country=TR&stars_min=4&limit=12');

  const hotelLinks = page.locator('a[href^="/hotels/"]');
  await expect(hotelLinks.first()).toBeVisible();
  expect(await hotelLinks.count()).toBeGreaterThan(0);

  await hotelLinks.first().click();
  await expect(page).toHaveURL(/\/hotels\//);
  await expect(page.locator('h1')).toBeVisible();
  await expect(page.getByRole('heading', { name: /Календар цін/ })).toBeVisible();
});

test('hotel nights selector only exposes Farvater calendar durations', async ({ page }) => {
  const refreshRequests: string[] = [];
  await page.route('**/api/hotels/*/refresh**', async (route) => {
    refreshRequests.push(route.request().url());
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ queued: true, eta_seconds: 1 }),
    });
  });

  await page.goto('/hotels/ci-e2e-kemer-resort');

  await expect(page.getByRole('heading', { name: 'CI E2E Kemer Resort' })).toBeVisible();

  for (const nights of [7, 8, 9, 10, 11, 12, 13, 14]) {
    await expect(page.getByRole('button', { name: `${nights} ноч.`, exact: true })).toBeVisible();
  }

  for (const nights of [3, 5, 21]) {
    await expect(page.getByRole('button', { name: `${nights} ноч.`, exact: true })).toHaveCount(0);
  }

  const customNights = page.getByLabel('Своя кількість ночей');
  await expect(customNights).toBeVisible();
  await expect(customNights).toHaveAttribute('min', '1');
  await expect(customNights).toHaveAttribute('max', '30');

  await page.getByRole('button', { name: '8 ноч.', exact: true }).click();
  await expect(page.getByRole('heading', { name: /Календар цін \(8 ночей/ })).toBeVisible();

  await customNights.fill('15');
  await customNights.press('Enter');
  await expect(page.getByRole('heading', { name: /Календар цін \(15 ночей/ })).toBeVisible();
  await expect
    .poll(() => refreshRequests.some((url) => new URL(url).searchParams.get('nights') === '15'))
    .toBe(true);
});

test('search results can be sorted and keep the choice in the URL', async ({ page }) => {
  await page.goto('/search?country=TR&nights=7&stars_min=4&adults=2&limit=12');

  const sortSelect = page.getByLabel('Сортування результатів');
  await expect(sortSelect).toBeVisible();
  await expect(sortSelect).toHaveValue('price_asc');

  await sortSelect.selectOption('rating_desc');

  await expect(page).toHaveURL(/sort=rating_desc/);
  await expect(page).not.toHaveURL(/offset=/);
  await expect(page.locator('a[href^="/hotels/"]').first()).toBeVisible();
});

test('old duplicate hotel slug redirects to the canonical hotel page', async ({ page }) => {
  await page.goto('/hotels/fv-es-apart-hotel-ght-tossa-park');

  await expect(page).toHaveURL(/\/hotels\/fv-es-tossa-park-aparthotel$/);
  await expect(page.getByRole('heading', { name: 'Tossa Park Aparthotel' })).toBeVisible();
  await expect(page.getByRole('heading', { name: /Календар цін/ })).toBeVisible();
});

test('deals page renders discounts with external buy links', async ({ page }) => {
  await page.goto('/deals');

  await expect(page).toHaveTitle(/Гарячі знижки на тури/);
  await expect(page.getByText(/-\d+%/).first()).toBeVisible();

  const buyLinks = page.getByRole('link', { name: /Купити/ });
  await expect(buyLinks.first()).toBeVisible();
  expect(await buyLinks.count()).toBeGreaterThan(0);
  await expect(buyLinks.first()).toHaveAttribute('href', /^https:\/\/farvater\.travel\//);
});

test('deal permalink keeps enriched hotel context and links back to the hotel page', async ({
  page,
}) => {
  await page.goto('/deals');

  const permalink = page.getByRole('link', { name: /Постійне посилання/ }).first();
  await expect(permalink).toBeVisible();
  const href = await permalink.getAttribute('href');
  expect(href).toMatch(/^\/deals\/\d+$/);
  const dealId = href!.split('/').pop()!;

  await permalink.click();

  await expect(page).toHaveURL(new RegExp(`/deals/${dealId}$`));
  await expect(page.locator('h1, a').filter({ hasText: /Готель #/ })).toHaveCount(0);
  await expect(page.locator('a[href^="/hotels/"]').first()).toBeVisible();
});

import { expect, test } from '@playwright/test';

test('global language follows navigation, keeps drafts and persists on reload', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: '工作台', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'EN', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await expect(page.getByRole('heading', { name: 'Overview', exact: true })).toBeVisible();
  const routes = [['/data', 'Data'], ['/dashboard', 'Dashboard'], ['/reports', 'Reports'], ['/operations', 'Operations'], ['/settings/models', 'Models']];
  for (const [route, heading] of routes) {
    await page.goto(route);
    await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'EN', exact: true })).toHaveAttribute('aria-pressed', 'true');
    if (route === '/dashboard') await expect(page.locator('.dashboard-filters')).toBeVisible();
    if (route === '/operations') await expect(page.locator('.ops-stats')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  await page.getByRole('button', { name: 'Add model', exact: true }).click();
  await page.getByLabel('Configuration name', { exact: true }).fill('Unsaved draft / 草稿');
  await page.getByLabel('Model name', { exact: true }).fill('example-model');
  await page.getByLabel('API Key', { exact: true }).fill('synthetic-unsaved-key');
  await page.getByRole('button', { name: '中文', exact: true }).click();
  await expect(page.getByLabel('配置名称', { exact: true })).toHaveValue('Unsaved draft / 草稿');
  await expect(page.getByLabel('模型名称', { exact: true })).toHaveValue('example-model');
  await page.getByRole('button', { name: 'EN', exact: true }).click();
  await expect(page.getByLabel('Configuration name', { exact: true })).toHaveValue('Unsaved draft / 草稿');
  await expect(page.getByLabel('API Key', { exact: true })).toHaveValue('synthetic-unsaved-key');
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain('synthetic-unsaved-key');
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Models', exact: true })).toBeVisible();
  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual(['shoppulse.language']);
  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'Data', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Data', exact: true })).toBeVisible();
  await page.goto('/does-not-exist');
  await expect(page.getByRole('heading', { name: 'Page not found', exact: true })).toBeVisible();
});

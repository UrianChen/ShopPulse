import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test } from '@playwright/test';
import { seed } from './fixtures';

test('real published snapshots drive all dashboard filters and quality states', async ({ page }) => {
  test.setTimeout(240000);
  await page.goto('/');
  await expect(page.getByRole('heading', { name: '工作台' })).toBeVisible();
  const costId = await seed(page, 'costs.csv', 'costs');
  const goldenId = await seed(page, 'orders.csv', 'orders', costId);
  const missingCost = readFileSync(resolve('../samples/costs.csv'), 'utf8').split(/\r?\n/).filter(line => !line.startsWith('B,')).join('\n');
  const partialCostId = await seed(page, 'costs.csv', 'costs', undefined, missingCost);
  const partialId = await seed(page, 'orders.csv', 'orders', partialCostId);
  const unknownId = await seed(page, 'orders.csv', 'orders', costId, undefined, true);

  await page.goto(`/dashboard?dataset=${goldenId}`);
  await expect(page.getByTestId('metric-net_sales').locator('.metric-value')).toContainText('550.00', { timeout: 30000 });
  await expect(page.getByTestId('metric-net_sales')).toContainText('+10.00%');
  await expect(page.getByTestId('metric-gross_profit').locator('.metric-value')).toContainText('230.00');
  await expect(page.getByTestId('metric-aov').locator('.metric-value')).toContainText('183.33');
  await expect(page.getByTestId('metric-paid_orders').locator('.metric-value')).toHaveText('3');
  await page.getByLabel('商品排序').selectOption('gross_profit');
  await expect(page.locator('.product-panel tbody tr').first().getByRole('button', { name: 'C', exact: true })).toBeVisible();
  await page.getByText('更多指标与计算口径', { exact: true }).click();
  await expect(page.locator('.extra-metrics')).toContainText('320.00');
  await expect(page.locator('.extra-metrics')).toContainText('15.38%');

  await page.getByLabel('SKU 筛选').fill('B');
  await page.getByRole('button', { name: '添加', exact: true }).click();
  await page.getByRole('button', { name: '更新看板' }).click();
  await expect(page.getByTestId('metric-net_sales').locator('.metric-value')).toContainText('150.00', { timeout: 30000 });
  await expect(page.locator('.product-panel tbody tr')).toHaveCount(1);
  await expect(page.getByTestId('metric-net_sales')).toContainText('上期为零');
  await page.reload();
  await expect(page.getByTestId('metric-net_sales').locator('.metric-value')).toContainText('150.00', { timeout: 30000 });
  await page.locator('.sku-chips button').click();
  await page.getByLabel('开始日期', { exact: true }).fill('2026-10-01');
  await page.getByLabel('结束日期（含当日）', { exact: true }).fill('2026-10-01');
  await page.getByLabel('比较周期').selectOption('none');
  await page.getByRole('button', { name: '更新看板' }).click();
  await expect(page.getByTestId('metric-net_sales').locator('.metric-value')).toContainText('0.00', { timeout: 30000 });
  await expect(page.getByTestId('metric-aov')).toContainText('分母为零');
  await expect(page.locator('.product-panel')).toContainText('当前范围或商品条件下没有记录');

  await page.getByLabel('数据版本').selectOption(goldenId);
  await page.getByLabel('比较周期').selectOption('custom');
  await page.getByLabel('比较开始', { exact: true }).fill('2026-09-14');
  await page.getByLabel('比较结束（含当日）', { exact: true }).fill('2026-09-20');
  await page.getByLabel('趋势粒度').selectOption('week');
  await page.getByRole('button', { name: '更新看板' }).click();
  await expect(page.getByTestId('metric-net_sales')).toContainText('覆盖不完整', { timeout: 30000 });
  await expect(page.getByTestId('metric-net_sales').locator('.metric-value')).toContainText('550.00');

  await page.getByLabel('数据版本').selectOption(partialId);
  await page.getByRole('button', { name: '更新看板' }).click();
  await expect(page.getByTestId('metric-gross_profit')).toContainText('成本未全部匹配', { timeout: 30000 });
  await expect(page.getByTestId('subset-net_sales')).toContainText('400.00');
  await expect(page.getByTestId('subset-net_cogs')).toContainText('220.00');
  await expect(page.getByTestId('subset-gross_profit')).toContainText('180.00');
  await page.getByLabel('数据版本').selectOption(unknownId);
  await page.getByRole('button', { name: '更新看板' }).click();
  await expect(page.getByTestId('metric-net_sales')).toContainText('累计退款未知', { timeout: 30000 });
  await expect(page.getByTestId('metric-gross_sales').locator('.metric-value')).toContainText('650.00');

  await page.getByLabel('数据版本').selectOption(goldenId);
  await page.getByRole('button', { name: '更新看板' }).click();
  await expect(page.getByTestId('metric-net_sales').locator('.metric-value')).toContainText('550.00', { timeout: 30000 });
});

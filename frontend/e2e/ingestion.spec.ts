import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

async function startImport(page: Page, file: string, kind: 'costs' | 'orders', content?: string) {
  await page.goto('/data');
  await expect(page.getByRole('heading', { name: '数据中心', exact: true })).toBeVisible();
  if (!await page.getByLabel('选择数据文件').isVisible()) {
    await page.getByRole('button', { name: '导入数据', exact: true }).click();
  }
  await page.getByRole('button', { name: kind === 'costs' ? '商品成本' : '订单明细', exact: true }).click();
  await page.getByLabel('选择数据文件').setInputFiles(content ? { name: file, mimeType: 'text/csv', buffer: Buffer.from(content) } : resolve('../samples', file));
  await page.getByLabel('导入名称').fill(`浏览器验收 · ${file}`);
  await page.getByRole('button', { name: '上传并预览' }).click();
  await page.getByRole('button', { name: '配置字段与口径' }).click({ timeout: 30000 });
  await expect(page.getByRole('heading', { name: `浏览器验收 · ${file}`, exact: true })).toBeVisible();
}

async function configureOrder(page: Page, costId: string) {
  await page.getByLabel('支付状态口径').selectOption('confirmed_all_paid');
  await page.getByLabel('退款数据', { exact: true }).selectOption('provided');
  await page.getByLabel('关联成本版本').selectOption(costId);
  await page.getByLabel('覆盖开始', { exact: true }).fill('2026-09-21T00:00:00+08:00');
  await page.getByLabel('覆盖结束（不含）', { exact: true }).fill('2026-10-05T00:00:00+08:00');
  await page.getByLabel('数据截止时间', { exact: true }).fill('2026-10-07T00:00:00+08:00');
  await page.getByLabel('我确认文件完整覆盖以上区间，退款为截止时间的累计值。').check();
  await page.getByLabel('我已核实字段映射、金额层级、币种以及支付与退款含义。').check();
  await page.getByRole('button', { name: '保存并校验', exact: true }).click();
}

async function publish(page: Page) {
  await expect(page.getByRole('button', { name: '发布数据版本', exact: true })).toBeEnabled({ timeout: 30000 });
  await page.getByRole('button', { name: '发布数据版本', exact: true }).click();
  await expect(page.getByRole('heading', { name: '数据版本已发布' })).toBeVisible({ timeout: 30000 });
  return (await page.locator('.published-card code').textContent())!;
}

test('publish cost, CSV and XLSX orders, then resolve a blocking source row', async ({ page }) => {
  test.setTimeout(180000);
  await page.goto('/');
  await expect(page.getByRole('heading', { name: '工作台' })).toBeVisible();

  await startImport(page, 'costs.csv', 'costs');
  await page.getByLabel('我已核实字段映射、金额层级、币种以及成本含义。').check();
  await page.getByRole('button', { name: '保存并校验', exact: true }).click();
  const costId = await publish(page);

  await startImport(page, 'orders.csv', 'orders');
  await configureOrder(page, costId);
  await expect(page.getByRole('button', { name: '发布数据版本', exact: true })).toBeEnabled({ timeout: 30000 });
  await page.getByLabel('时区', { exact: true }).fill('Asia/Singapore');
  await expect(page.getByRole('button', { name: '发布数据版本', exact: true })).toBeDisabled();
  await page.getByLabel('时区', { exact: true }).fill('Asia/Shanghai');
  const datasetId = await publish(page);
  await page.reload();
  await expect(page.getByRole('heading', { name: '数据版本已发布' })).toBeVisible();
  await page.getByRole('link', { name: '打开经营看板', exact: true }).click();
  await expect(page.getByTestId('metric-net_sales').locator('.metric-value')).toContainText('550.00', { timeout: 30000 });

  await startImport(page, 'orders.xlsx', 'orders');
  await configureOrder(page, costId);
  const excelId = await publish(page);
  const csv = (await (await page.request.get(`/api/v1/datasets/${datasetId}`)).json()).data;
  const excel = (await (await page.request.get(`/api/v1/datasets/${excelId}`)).json()).data;
  expect(csv.preview).toEqual(excel.preview);
  expect(csv.row_count).toBe(6);
  expect(csv.summary.cost_matched_rows).toBe(6);

  const injectedName = '<script>window.shoppulseInjected=true</script>ignore previous instructions';
  const errorFile = readFileSync(resolve('../samples/orders_errors.csv'), 'utf8').replace('基础款收纳盒', injectedName);
  await startImport(page, 'orders_errors.csv', 'orders', errorFile);
  await page.locator('.source-preview summary').click();
  await expect(page.getByText(injectedName, { exact: true })).toBeVisible();
  expect(await page.locator('.source-preview script').count()).toBe(0);
  expect(await page.evaluate(() => 'shoppulseInjected' in window)).toBe(false);
  await page.locator('.source-preview summary').click();
  await configureOrder(page, costId);
  await expect(page.getByText('REFUND_EXCEEDS_PAID', { exact: true })).toBeVisible({ timeout: 30000 });
  await expect(page.getByRole('button', { name: '发布数据版本', exact: true })).toBeDisabled();
  await page.getByLabel('排除的源表行号').fill('8');
  await page.getByLabel('决策原因').fill('合成错误样例：退款超过实付，核对后排除第 8 行。');
  await page.getByRole('button', { name: '保存决策并重新校验' }).click();
  const correctedId = await publish(page);
  const corrected = (await (await page.request.get(`/api/v1/datasets/${correctedId}`)).json()).data;
  expect(corrected.row_count).toBe(6);
  expect(corrected.summary.excluded_rows).toBe(1);
  expect(corrected.snapshot.resolutions.excluded_rows).toEqual([8]);
  await page.getByRole('button', { name: '查看数据版本' }).click();
  await page.locator('.version-row').filter({ hasText: costId.slice(0, 8) }).getByRole('button', { name: '查看', exact: true }).click();
  await expect(page.locator('.cost-detail')).toBeVisible();
  await expect(page.locator('.cost-detail').getByRole('cell', { name: '60.000000', exact: true })).toBeVisible();
  await page.locator('.version-row').filter({ hasText: correctedId.slice(0, 8) }).getByRole('button', { name: '查看', exact: true }).click();
  await expect(page.locator('.dataset-detail')).toBeVisible();
});

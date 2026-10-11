import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';
import { seed } from './fixtures';

test('offline exports, keyboard evidence, configuration revision and reviewed deletion', async ({ page }) => {
  test.setTimeout(180000);
  await page.goto('/');
  await expect(page.getByRole('heading', { name: '工作台' })).toBeVisible();
  const dataset = await seed(page, 'orders.csv', 'orders', await seed(page, 'costs.csv', 'costs'));
  const headers = { Origin: new URL(page.url()).origin, 'Idempotency-Key': crypto.randomUUID() };
  const created = await page.request.post('/api/v1/reports', { headers, data: { title: '导出与删除测试', query: { dataset_id: dataset, start: '2026-09-28', end_exclusive: '2026-10-05' } } });
  expect(created.status()).toBe(202);
  const report = (await created.json()).data;
  await page.goto(`/reports/${report.id}`);
  await expect(page.locator('.report-status')).toContainText('已完成', { timeout: 45000 });
  await page.getByRole('button', { name: '查看证据', exact: true }).first().click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).not.toBeVisible();
  for (const format of ['html', 'markdown', 'pdf']) {
    await page.getByLabel('导出格式').selectOption(format);
    await page.getByRole('button', { name: '生成导出', exact: true }).click();
    const link = page.getByRole('link', { name: `下载 ${format.toUpperCase()}`, exact: true });
    await expect(link).toBeVisible({ timeout: 45000 });
    const downloaded = page.waitForEvent('download');
    await link.click();
    const file = await downloaded;
    expect(await file.failure()).toBeNull();
    if (format === 'html') {
      const html = readFileSync((await file.path())!, 'utf8');
      expect(html).toContain('CNY 550.00');
      expect(html).toContain('CNY 230.00');
      expect(html).not.toContain('<script');
    }
  }
  await page.goto('/operations');
  await expect(page.getByRole('heading', { name: '运行管理' })).toBeVisible();
  const original = (await (await page.request.get('/api/v1/operations/settings')).json()).data;
  await page.getByLabel('店铺名称', { exact: true }).fill(original.name);
  await page.getByRole('button', { name: '保存设置', exact: true }).click();
  await expect(page.getByText(`修订 ${original.revision + 1}。`, { exact: false })).toBeVisible();
  await page.getByRole('button', { name: '预览到期清理' }).click();
  await expect(page.getByRole('heading', { name: '请核对本次影响' })).toBeVisible();
  await expect(page.getByRole('button', { name: '执行已预览操作' })).toBeDisabled();
  await page.getByRole('button', { name: '返回', exact: true }).click();
  // Only delete this test's synthetic report, never a user report or global cleanup scope.
  await page.getByLabel('对象 ID').fill(report.id);
  await page.getByRole('button', { name: '预览删除影响' }).click();
  await expect(page.locator('.deletion-preview')).toContainText('报告及证据/追问：1');
  await page.getByLabel('输入“确认删除”以执行').fill('确认删除');
  await page.getByRole('button', { name: '执行已预览操作' }).click();
  await expect(page.getByRole('status')).toContainText('操作已完成');
  expect((await page.request.get(`/api/v1/reports/${report.id}`)).status()).toBe(404);
  expect((await page.request.get(`/api/v1/datasets/${dataset}`)).status()).toBe(200);
});

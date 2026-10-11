import { expect, test } from '@playwright/test';

test('model settings: encryption state, capabilities, fallback, failure, edit and clear', async ({ page }) => {
  test.skip(!process.env.E2E_MODEL_BASE_URL, 'Start compose.mock.yaml and set E2E_MODEL_BASE_URL.');
  test.setTimeout(150000);
  await page.goto('/');
  await page.getByRole('link', { name: '模型设置' }).click();
  const suffix = Date.now().toString();
  const key = 'synthetic-browser-test-key-only';
  const names: string[] = [];
  const create = async (model: string, title: string) => {
    const name = `${title}-${suffix}`;
    names.push(name);
    await page.getByRole('button', { name: '添加模型', exact: true }).click();
    await page.getByLabel('配置名称', { exact: true }).fill(name);
    await page.getByLabel('模型名称', { exact: true }).fill(model);
    await page.getByLabel('API 根地址').fill(process.env.E2E_MODEL_BASE_URL!);
    await page.getByLabel('API Key', { exact: true }).fill(key);
    await page.getByLabel('我同意向该服务发送上述数据。').check();
    const response = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/model-configs'));
    await page.getByRole('button', { name: '保存配置' }).click();
    expect(await (await response).text()).not.toContain(key);
    await expect(page.getByRole('heading', { name: '添加模型配置' })).not.toBeVisible();
    const card = page.getByRole('article', { name, exact: true });
    await expect(card.getByText('密钥已保存', { exact: true })).toBeVisible();
    await card.getByRole('button', { name: '测试连接' }).click();
    return card;
  };
  const full = await create('full', '完整能力');
  await expect(full.getByText('原生工具调用', { exact: true })).toBeVisible({ timeout: 30000 });
  await full.getByRole('button', { name: '编辑', exact: true }).click();
  await expect(page.getByLabel('API Key', { exact: true })).toHaveValue('');
  await page.getByLabel('我同意向该服务发送上述数据。').check();
  await page.getByRole('button', { name: '保存配置' }).click();
  await expect(full.getByText('版本 2')).toBeVisible();
  await expect(full.getByText('密钥已保存', { exact: true })).toBeVisible();
  await full.getByRole('button', { name: '测试连接' }).click();
  await expect(full.getByText('原生工具调用', { exact: true })).toBeVisible({ timeout: 30000 });
  const limited = await create('no-tools', '兼容模式');
  await expect(limited.getByText('受限 JSON 模式', { exact: true })).toBeVisible({ timeout: 30000 });
  const failed = await create('auth-fail', '认证失败');
  await expect(failed.getByText('连接不可用', { exact: true })).toBeVisible({ timeout: 30000 });
  await expect(failed.getByText(/认证失败，请检查 API Key/)).toBeVisible();
  await page.reload();
  await expect(full.getByText('原生工具调用', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0);
  await full.getByRole('button', { name: '编辑', exact: true }).click();
  await page.getByLabel('清除已保存的 API Key', { exact: true }).check();
  await page.getByLabel('我同意向该服务发送上述数据。').check();
  await page.getByRole('button', { name: '保存配置' }).click();
  await expect(full.getByText('未设置密钥', { exact: true })).toBeVisible();
  for (const name of names) {
    const card = page.getByRole('article', { name, exact: true });
    await card.getByRole('button', { name: '删除', exact: true }).click();
    await card.getByRole('button', { name: '确认删除', exact: true }).click();
    await expect(card).not.toBeVisible();
  }
});

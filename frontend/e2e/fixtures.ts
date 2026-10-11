import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, type Page } from '@playwright/test';

export async function seed(page: Page, filename: string, kind: 'costs' | 'orders', costId?: string, content?: string, refundUnknown = false) {
  const headers = { Origin: new URL(page.url()).origin };
  const uploaded = await page.request.post('/api/v1/uploads', { headers, multipart: { kind, file: { name: filename, mimeType: 'text/csv', buffer: content ? Buffer.from(content) : readFileSync(resolve('../samples', filename)) } } });
  expect(uploaded.status()).toBe(202);
  const uploadId = (await uploaded.json()).data.upload_id;
  await expect.poll(async () => (await (await page.request.get(`/api/v1/uploads/${uploadId}`)).json()).data.status, { timeout: 30000 }).toBe('ready');
  let draft = (await (await page.request.post('/api/v1/imports', { headers, data: { upload_id: uploadId, name: `看板验收 · ${filename}${refundUnknown ? ' · 退款未知' : ''}` } })).json()).data;
  const cfg = draft.config;
  cfg.options.semantics_confirmed = true;
  if (kind === 'orders') {
    cfg.cost_version_id = costId;
    Object.assign(cfg.options, { payment_state_mode: 'confirmed_all_paid', refund_mode: refundUnknown ? 'unknown' : 'provided', coverage_start: '2026-09-21T00:00:00+08:00', coverage_end_exclusive: '2026-10-05T00:00:00+08:00', source_as_of: '2026-10-07T00:00:00+08:00', coverage_confirmed: true });
  }
  const path = `/api/v1/imports/${draft.id}`;
  draft = (await (await page.request.put(path + '/mapping', { headers, data: { expected_revision: draft.revision, config: cfg } })).json()).data;
  async function validate() {
    expect((await page.request.post(path + '/validate', { headers, data: { expected_revision: draft.revision } })).status()).toBe(202);
    await expect.poll(async () => { draft = (await (await page.request.get(path)).json()).data; return draft.status; }, { timeout: 30000 }).toMatch(/^(ready|review_required)$/);
  }
  await validate();
  if (draft.status === 'review_required') {
    expect(draft.summary.errors).toBe(0);
    draft = (await (await page.request.put(path + '/resolutions', { headers, data: { expected_revision: draft.revision, acknowledged_codes: draft.summary.warning_codes, excluded_rows: [], reason: '合成验收数据：明确接受缺失成本或退款未知，验证指标降级。' } })).json()).data;
    await validate();
  }
  expect(draft.status).toBe('ready');
  expect((await page.request.post(path + '/publish', { headers, data: { expected_revision: draft.revision } })).status()).toBe(202);
  await expect.poll(async () => { draft = (await (await page.request.get(path)).json()).data; return draft.status; }, { timeout: 30000 }).toBe('published');
  return draft.published_id as string;
}


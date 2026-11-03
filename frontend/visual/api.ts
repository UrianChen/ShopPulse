import { readFileSync } from 'node:fs';
import type { Page } from '@playwright/test';

/** The fixture entries the tests navigate by; the rest are only served. */
type Fixtures = Record<string, unknown> & {
  '/reports': { items: { id: string }[] };
  '/imports': { id: string; kind: string }[];
};

/** Responses of the real API by path, written by backend/tests/test_visual_fixtures.py. */
export const responses: Fixtures = JSON.parse(
  readFileSync(new URL('../src/test/api.json', import.meta.url), 'utf8'),
);

export const ids = {
  /** The latest report: a revision that rechecks its parent's hypotheses. */
  report: responses['/reports'].items[0].id,
  ordersImport: responses['/imports'].find(d => d.kind === 'orders')!.id,
};

/**
 * Answer `/api/v1` from the fixtures: GETs by path (the query is ignored) and the dashboard's
 * metric query. Returns the requests without a fixture, so a test notices an incomplete page.
 */
export async function serveApi(page: Page) {
  const missing: string[] = [];
  await page.route('**/api/v1/**', route => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api\/v1/, '');
    const method = request.method();
    const served = method === 'GET' || (method === 'POST' && path === '/metrics/query');
    if (served && path in responses) {
      return route.fulfill({ json: { data: responses[path], meta: { request_id: 'visual' } } });
    }
    missing.push(`${method} ${path}`);
    const error = { code: 'NOT_FOUND', message: 'No fixture.', retryable: false };
    return route.fulfill({ status: 404, json: { error, meta: { request_id: 'visual' } } });
  });
  return missing;
}

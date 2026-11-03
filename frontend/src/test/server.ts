// The API for component tests: an MSW server answering `/api/v1` with the responses recorded from
// the real API (api.json, written by backend/tests/test_visual_fixtures.py; the visual tests serve
// the same file). Tests replace single responses with `serveApi`; a request that nothing answers
// fails the test.
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import type { Paged } from '../lib/types';
import recorded from './api.json';

const responses: Record<string, unknown> = recorded;

/** The latest recorded report: an agent v3 revision that rechecks its parent's hypotheses. */
export const recordedReportId = (recorded['/reports'] satisfies Paged<{ id: string }>).items[0].id;

function envelope(data: unknown) {
  return HttpResponse.json({ data, meta: { request_id: 'test' } });
}

export const server = setupServer(
  http.get('/api/v1/*', ({ request }) => {
    const path = new URL(request.url).pathname.replace(/^\/api\/v1/, '');
    return path in responses ? envelope(responses[path]) : undefined;
  }),
);

/** Answer GET `path` (with any query) with `data` for the current test. */
export function serveApi(routes: Record<string, unknown>) {
  server.use(
    ...Object.entries(routes).map(([path, data]) =>
      http.get(`/api/v1${path}`, () => envelope(data)),
    ),
  );
}

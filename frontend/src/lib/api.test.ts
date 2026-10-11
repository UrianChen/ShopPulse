import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from './api';

afterEach(() => { vi.unstubAllGlobals(); });

describe('API transport', () => {
  it('sends direct requests and unwraps responses', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ data: { ok: true } })));
    vi.stubGlobal('fetch', fetch);
    expect(await api('/reports', { method: 'POST', body: '{}' })).toEqual({ ok: true });
    const options = fetch.mock.calls[0][1];
    expect(options.headers.get('Content-Type')).toBe('application/json');
    expect(options.credentials).toBe('omit');
  });
  it('exposes a safe error with a traceable request ID', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: { code: 'INVALID_QUERY', message: '查询参数无效。' },
      meta: { request_id: 'trace-id' },
    }), { status: 422 })));
    await expect(api('/metrics')).rejects.toMatchObject({
      status: 422, code: 'INVALID_QUERY', requestId: 'trace-id',
    });
  });
  it('handles network failures and empty delete responses', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('internal network info')));
    await expect(api('/workspace')).rejects.toBeInstanceOf(ApiError);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    expect(await api('/model-configs/example', { method: 'DELETE' })).toBeUndefined();
  });
});

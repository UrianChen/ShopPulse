export class ApiError extends Error {
  status: number;
  code: string;
  requestId?: string;
  constructor(status: number, code: string, message: string, requestId?: string) {
    super(message);
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      ...options, headers, credentials: 'omit',
      signal: options.signal ?? AbortSignal.timeout(15000),
    });
  } catch {
    throw new ApiError(0, 'NETWORK_ERROR', '服务暂时无法连接，请检查服务状态后重试。');
  }
  if (response.status === 204) return undefined as T;
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(
      response.status,
      body?.error?.code ?? 'SERVER_ERROR',
      body?.error?.message ?? '请求未能完成，请稍后重试。',
      body?.meta?.request_id,
    );
  }
  if (!body || !('data' in body)) {
    throw new ApiError(502, 'INVALID_RESPONSE', '服务返回了无法识别的响应。');
  }
  return body.data as T;
}

export type Workspace = { id: string; name: string; timezone: string; currency: string };

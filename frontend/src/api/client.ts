const API_ROOT = '/api';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId?: string;
  readonly details?: unknown;

  constructor(
    message: string,
    options: { status: number; code: string; requestId?: string; details?: unknown },
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = options.status;
    this.code = options.code;
    if (options.requestId !== undefined) this.requestId = options.requestId;
    if (options.details !== undefined) this.details = options.details;
  }
}

export function isDisconnectedError(error: unknown): boolean {
  return error instanceof TypeError || (error instanceof DOMException && error.name === 'AbortError');
}

async function parseBody(response: Response): Promise<unknown> {
  if (response.status === 204) return undefined;
  const text = await response.text();
  if (text.length === 0) return undefined;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new ApiError('The server returned an unreadable response.', {
      status: response.status,
      code: 'invalid_response',
    });
  }
}

function toApiError(response: Response, body: unknown): ApiError {
  const candidate =
    typeof body === 'object' && body !== null && 'error' in body ? body.error : undefined;
  if (typeof candidate === 'object' && candidate !== null) {
    const message = 'message' in candidate ? candidate.message : undefined;
    const code = 'code' in candidate ? candidate.code : undefined;
    const requestId = 'request_id' in candidate ? candidate.request_id : undefined;
    const details = 'details' in candidate ? candidate.details : undefined;
    if (typeof message === 'string' && typeof code === 'string') {
      return new ApiError(message, {
        status: response.status,
        code,
        ...(typeof requestId === 'string' ? { requestId } : {}),
        ...(details !== undefined ? { details } : {}),
      });
    }
  }
  return new ApiError(`Request failed with status ${String(response.status)}.`, {
    status: response.status,
    code: 'request_failed',
  });
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('Accept', 'application/json');
  if (init.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    credentials: 'same-origin',
    headers,
  });
  const body = await parseBody(response);
  if (!response.ok) throw toApiError(response, body);
  return body as T;
}

export async function apiRequestWithStatus<T>(
  path: string,
  acceptedStatuses: readonly number[],
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('Accept', 'application/json');
  const response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    credentials: 'same-origin',
    headers,
  });
  const body = await parseBody(response);
  if (!response.ok && !acceptedStatuses.includes(response.status)) throw toApiError(response, body);
  return body as T;
}

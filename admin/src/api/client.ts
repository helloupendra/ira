// One fetch wrapper for the whole console. Every call carries the session
// cookie and the X-Ira-Request header the server checks on writes.

export type Query = Record<string, string | number | boolean | null | undefined>;

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  json?: unknown;
  query?: Query;
  signal?: AbortSignal;
}

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly body: unknown;

  constructor(status: number, detail: string, body: unknown = null) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.body = body;
  }
}

// Fired on any 401 so the session can flip to anonymous wherever it came from.
export const UNAUTHORIZED_EVENT = 'ira:unauthorized';

export function buildQuery(query?: Query): string {
  if (!query) return '';
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null) continue;
    params.set(key, String(value));
  }
  const s = params.toString();
  return s ? `?${s}` : '';
}

function fallbackDetail(status: number): string {
  if (status === 401) return 'Please sign in';
  if (status === 403) return 'Not allowed for your role';
  if (status === 404) return 'Not found';
  if (status === 429) return 'Too many requests';
  if (status >= 500) return `The server had a problem (${status})`;
  return `Request failed (${status})`;
}

// The parts of a location worth showing: "body.password" reads as "password".
function locationOf(loc: unknown): string {
  if (!Array.isArray(loc)) return '';
  return loc
    .filter((part, i) => !(i === 0 && ['body', 'query', 'path', 'header'].includes(String(part))))
    .map(String)
    .join('.');
}

export function detailFrom(body: unknown, status: number): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === 'string' && detail) return detail;
    if (Array.isArray(detail)) {
      const parts = detail.map((item: unknown) => {
        if (!item || typeof item !== 'object') return String(item);
        const { msg, loc } = item as { msg?: unknown; loc?: unknown };
        const where = locationOf(loc);
        const text = typeof msg === 'string' ? msg : 'invalid';
        return where ? `${where}: ${text}` : text;
      });
      if (parts.length) return parts.join('; ');
    }
  }
  return fallbackDetail(status);
}

async function readBody(response: Response): Promise<unknown> {
  if (response.status === 204) return undefined;
  const text = await response.text();
  if (!text) return undefined;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

// A page of rows plus whether the server has more after it (the X-Has-More
// header every paged list sends).
export interface Page<T> {
  rows: T;
  hasMore: boolean;
}

export async function requestPage<T>(path: string, options: RequestOptions = {}): Promise<Page<T>> {
  const { body, headers } = await requestWithHeaders<T>(path, options);
  return { rows: body, hasMore: headers.get('x-has-more') === 'true' };
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return (await requestWithHeaders<T>(path, options)).body;
}

export async function requestWithHeaders<T>(
  path: string,
  options: RequestOptions = {},
): Promise<{ body: T; headers: Headers }> {
  const { method = 'GET', json, query, signal } = options;
  const headers: Record<string, string> = { 'X-Ira-Request': '1', Accept: 'application/json' };
  const init: RequestInit = { method, headers, credentials: 'same-origin', signal };
  if (json !== undefined) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(json);
  }

  let response: Response;
  try {
    response = await fetch(path + buildQuery(query), init);
  } catch (err) {
    if ((err as { name?: string }).name === 'AbortError') throw err;
    throw new ApiError(0, 'Cannot reach the server');
  }

  const body = await readBody(response);
  if (!response.ok) {
    if (response.status === 401 && typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
    }
    throw new ApiError(response.status, detailFrom(body, response.status), body);
  }
  return { body: body as T, headers: response.headers };
}

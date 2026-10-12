import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, UNAUTHORIZED_EVENT, buildQuery, detailFrom, request } from './client';

type Fetch = (input: string, init: RequestInit) => Promise<Response>;

function reply(body: unknown, status = 200): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function stubFetch(impl: Fetch) {
  const mock = vi.fn<Fetch>(impl);
  vi.stubGlobal('fetch', mock);
  return mock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('request', () => {
  it('sends the CSRF header and the session cookie', async () => {
    const fetch = stubFetch(async () => reply({ ok: true }));
    await request('/v1/auth/logout', { method: 'POST' });
    const [url, init] = fetch.mock.calls[0]!;
    expect(url).toBe('/v1/auth/logout');
    expect(init.method).toBe('POST');
    expect(init.credentials).toBe('same-origin');
    expect((init.headers as Record<string, string>)['X-Ira-Request']).toBe('1');
  });

  it('sends JSON bodies and returns parsed JSON', async () => {
    const fetch = stubFetch(async () => reply({ user: { id: 1 } }));
    const result = await request<{ user: { id: number } }>('/v1/auth/login', {
      method: 'POST',
      json: { email: 'owner@example.com', password: 'x' },
    });
    const [, init] = fetch.mock.calls[0]!;
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json');
    expect(init.body).toBe('{"email":"owner@example.com","password":"x"}');
    expect(result.user.id).toBe(1);
  });

  it('builds the query string and skips empty values', async () => {
    const fetch = stubFetch(async () => reply([]));
    await request('/v1/admin/calls', { query: { limit: 5, before_id: undefined, status: null, q: 'a b' } });
    expect(fetch.mock.calls[0]![0]).toBe('/v1/admin/calls?limit=5&q=a+b');
    expect(buildQuery({})).toBe('');
    expect(buildQuery({ ok: false })).toBe('?ok=false');
  });

  it('returns undefined for an empty response', async () => {
    stubFetch(async () => new Response(null, { status: 204 }));
    await expect(request('/v1/x')).resolves.toBeUndefined();
  });

  it('throws ApiError with the detail string', async () => {
    stubFetch(async () => reply({ detail: 'wrong email or password' }, 401));
    vi.stubGlobal('window', { dispatchEvent: vi.fn() });
    const err = await request('/v1/auth/login', { method: 'POST', json: {} }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(401);
    expect((err as ApiError).detail).toBe('wrong email or password');
    expect((err as ApiError).body).toEqual({ detail: 'wrong email or password' });
  });

  it('joins validation errors into one sentence', async () => {
    stubFetch(async () =>
      reply(
        {
          detail: [
            { type: 'missing', loc: ['body', 'password'], msg: 'Field required' },
            { type: 'int_parsing', loc: ['query', 'limit'], msg: 'Input should be a valid integer' },
          ],
        },
        422,
      ),
    );
    const err = (await request('/v1/x').catch((e: unknown) => e)) as ApiError;
    expect(err.status).toBe(422);
    expect(err.detail).toBe('password: Field required; limit: Input should be a valid integer');
  });

  it('falls back to a plain sentence when the body is not JSON', async () => {
    stubFetch(async () => new Response('<html>bad gateway</html>', { status: 502 }));
    const err = (await request('/v1/x').catch((e: unknown) => e)) as ApiError;
    expect(err.status).toBe(502);
    expect(err.detail).toBe('The server had a problem (502)');
    expect(err.body).toBe('<html>bad gateway</html>');
  });

  it('announces a 401 before throwing', async () => {
    stubFetch(async () => reply({ detail: 'session expired' }, 401));
    const dispatchEvent = vi.fn();
    vi.stubGlobal('window', { dispatchEvent });
    await expect(request('/v1/auth/me')).rejects.toBeInstanceOf(ApiError);
    expect(dispatchEvent).toHaveBeenCalledTimes(1);
    expect((dispatchEvent.mock.calls[0]![0] as Event).type).toBe(UNAUTHORIZED_EVENT);
  });

  it('does not announce other errors', async () => {
    stubFetch(async () => reply({ detail: "this credential lacks 'admin.read'" }, 403));
    const dispatchEvent = vi.fn();
    vi.stubGlobal('window', { dispatchEvent });
    await expect(request('/v1/admin/overview')).rejects.toMatchObject({ status: 403 });
    expect(dispatchEvent).not.toHaveBeenCalled();
  });

  it('turns a network failure into status 0', async () => {
    stubFetch(async () => {
      throw new TypeError('fetch failed');
    });
    const err = (await request('/v1/x').catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(0);
    expect(err.detail).toBe('Cannot reach the server');
  });

  it('lets an abort through untouched', async () => {
    stubFetch(async () => {
      const e = new Error('aborted');
      e.name = 'AbortError';
      throw e;
    });
    const err = (await request('/v1/x').catch((e: unknown) => e)) as Error;
    expect(err).not.toBeInstanceOf(ApiError);
    expect(err.name).toBe('AbortError');
  });
});

describe('detailFrom', () => {
  it('uses the status when there is no detail', () => {
    expect(detailFrom(undefined, 404)).toBe('Not found');
    expect(detailFrom({ detail: '' }, 429)).toBe('Too many requests');
    expect(detailFrom({ detail: [] }, 400)).toBe('Request failed (400)');
  });
});

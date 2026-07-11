import { ApiError, apiRequest } from '../src/api/client';
import { api } from '../src/api/network';
import type { HealthResponse } from '../src/types/api';

describe('typed API client', () => {
  it('maps the backend error envelope without exposing an unreadable response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: 'connection_failed',
              message: 'The read-only connection could not be established.',
              request_id: 'req-123',
            },
          }),
          { status: 422, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    );

    const result = apiRequest('/devices/connection-test');
    await expect(result).rejects.toMatchObject({
      name: 'ApiError',
      status: 422,
      code: 'connection_failed',
      requestId: 'req-123',
    } satisfies Partial<ApiError>);
  });

  it('accepts a structured health response on HTTP 503 for service diagnostics', async () => {
    const health: HealthResponse = {
      status: 'unavailable',
      version: '0.1.0',
      checks: {
        database: { status: 'unavailable' },
        redis: { status: 'ok' },
        worker: { status: 'unavailable' },
      },
    };
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(health), {
          status: 503,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    );

    await expect(api.health()).resolves.toEqual(health);
  });

  it('uses relative API URLs and same-origin cookies', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ configured: false }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await api.setupStatus();

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/setup',
      expect.objectContaining({ credentials: 'same-origin' }),
    );
  });

  it('omits the display name from the strict connection-test request schema', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          reachable: true,
          driver: 'cisco_iosxe',
          message: 'SSH connection succeeded',
          latency_ms: 8,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    vi.stubGlobal('fetch', fetchMock);

    await api.testCandidateConnection({
      name: 'Display only',
      management_address: '192.0.2.10',
      port: 22,
      vendor: 'cisco_iosxe',
      credential_profile_id: 'c6d6a5be-bf2e-4d6a-bda8-3a559f985631',
    });

    const request = fetchMock.mock.calls[0]?.[1] as RequestInit;
    const body = JSON.parse(request.body as string) as unknown;
    expect(body).toEqual({
      management_address: '192.0.2.10',
      port: 22,
      vendor: 'cisco_iosxe',
      credential_profile_id: 'c6d6a5be-bf2e-4d6a-bda8-3a559f985631',
    });
  });
});

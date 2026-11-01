import { describe, expect, it } from 'vitest';
import { groupSessions, groupSpan } from './groups';

const row = (id: string, device: string, extra: Partial<{ current: boolean; created_at: number; last_used_at: number | null; expires_at: number }> = {}) => ({
  id,
  device,
  current: false,
  created_at: 100,
  last_used_at: null,
  expires_at: 1000,
  ...extra,
});

describe('groupSessions', () => {
  it('puts the same device together, in the order each first came', () => {
    const rows = [row('a', 'Chrome'), row('b', 'Safari'), row('c', 'Chrome'), row('d', 'Chrome')];
    const groups = groupSessions(rows, (r) => r.device);
    expect(groups.map((g) => [g.key, g.rows.map((r) => r.id)])).toEqual([
      ['Chrome', ['a', 'c', 'd']],
      ['Safari', ['b']],
    ]);
  });

  it('keeps this device on its own, even beside others like it', () => {
    const rows = [row('me', 'Chrome', { current: true }), row('a', 'Chrome'), row('b', 'Chrome')];
    const groups = groupSessions(rows, (r) => r.device);
    expect(groups.map((g) => g.rows.map((r) => r.id))).toEqual([['me'], ['a', 'b']]);
  });
});

describe('groupSpan', () => {
  it('gives the newest and oldest sign-in, the latest use and the last expiry', () => {
    const span = groupSpan([
      row('a', 'x', { created_at: 10, last_used_at: null, expires_at: 500 }),
      row('b', 'x', { created_at: 30, last_used_at: 40, expires_at: 700 }),
      row('c', 'x', { created_at: 20, last_used_at: 25, expires_at: 600 }),
    ]);
    expect(span).toEqual({ newest: 30, oldest: 10, lastUsed: 40, expires: 700 });
  });

  it('has no last use when none was used', () => {
    expect(groupSpan([row('a', 'x')]).lastUsed).toBeNull();
  });
});

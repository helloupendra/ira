import { describe, expect, it } from 'vitest';
import { ApiError } from '../../api/client';
import { failure, kindBadge, listed, switchedToast } from './helpers';

describe('kindBadge', () => {
  it('colours reads and actions differently', () => {
    expect(kindBadge('read')).toBe('badge badge-accent');
    expect(kindBadge('action')).toBe('badge badge-warn');
    expect(kindBadge('other')).toBe('badge badge-muted');
  });
});

describe('listed', () => {
  it('joins roles the way a sentence would', () => {
    expect(listed([])).toBe('');
    expect(listed(['owner'])).toBe('owner');
    expect(listed(['owner', 'admin'])).toBe('owner or admin');
    expect(listed(['owner', 'admin', 'staff'])).toBe('owner, admin or staff');
  });
});

describe('switchedToast', () => {
  it('says what switching off means', () => {
    expect(switchedToast('find_slots', true)).toBe('find slots is on.');
    expect(switchedToast('find_slots', false)).toBe("find slots is off. Ira won't see it until it is on again.");
  });
});

describe('failure', () => {
  it("shows the server's detail, or a sentence when there is none", () => {
    expect(failure(new ApiError(403, 'Not allowed for your role'))).toBe('Not allowed for your role');
    expect(failure(new ApiError(0, 'Cannot reach the server'))).toBe(
      'Cannot reach the server. Check the connection and try again.',
    );
    expect(failure(new Error('boom'))).toBe('boom');
    expect(failure('x')).toBe('Something went wrong.');
  });
});

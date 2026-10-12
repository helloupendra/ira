import { describe, expect, it } from 'vitest';
import { ApiError } from '../../api/client';
import {
  currentFirst,
  deviceLabel,
  deviceName,
  endedText,
  failure,
  lockedLine,
  pinFailure,
  pinHint,
  pinLine,
  pinPattern,
  plain,
  plural,
  scopeList,
} from './text';

// Node applies a change to TZ at once; the formatters are built per call.
process.env.TZ = 'UTC';

// Monday 12 October 2026, 14:32 UTC.
const NOW = Date.UTC(2026, 9, 12, 14, 32) / 1000;

const CHROME =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36';

describe('deviceName', () => {
  it('cuts a long user agent and keeps a short one', () => {
    const cut = deviceName(CHROME);
    expect(cut.length).toBeLessThanOrEqual(61);
    expect(cut.startsWith('Mozilla/5.0 (Macintosh')).toBe(true);
    expect(cut.endsWith('…')).toBe(true);
    expect(deviceName('curl/8.7.1')).toBe('curl/8.7.1');
  });

  it('says unknown when none was sent', () => {
    expect(deviceName(null)).toBe('unknown');
    expect(deviceName(undefined)).toBe('unknown');
    expect(deviceName('   ')).toBe('unknown');
  });
});

describe('deviceLabel', () => {
  it('shows the label the server read from the user agent', () => {
    expect(deviceLabel({ device: 'Chrome on macOS', user_agent: CHROME })).toBe('Chrome on macOS');
    expect(deviceLabel({ device: 'curl', user_agent: 'curl/8.7.1' })).toBe('curl');
  });

  it('falls back to the user agent, then to unknown', () => {
    expect(deviceLabel({ device: null, user_agent: 'curl/8.7.1' })).toBe('curl/8.7.1');
    expect(deviceLabel({ device: '  ', user_agent: null })).toBe('unknown');
    expect(deviceLabel({})).toBe('unknown');
  });
});

describe('scopeList', () => {
  it('reads comma text and lists alike', () => {
    expect(scopeList('ask,admin.read')).toBe('ask, admin.read');
    expect(scopeList(' ask , voice ')).toBe('ask, voice');
    expect(scopeList(['ask', 'voice'])).toBe('ask, voice');
    expect(scopeList('')).toBe('');
  });
});

describe('currentFirst', () => {
  it('puts this session first and keeps the rest in order', () => {
    const rows = [
      { id: 'a', current: false },
      { id: 'b', current: true },
      { id: 'c', current: false },
    ];
    expect(currentFirst(rows).map((r) => r.id)).toEqual(['b', 'a', 'c']);
    expect(rows[0]?.id).toBe('a');
  });
});

describe('plain and plural', () => {
  it('writes config numbers as a person would', () => {
    expect(plain(15.0)).toBe('15');
    expect(plain(2.5)).toBe('2.5');
    expect(plural(14, 'day')).toBe('14 days');
    expect(plural(1, 'day')).toBe('1 day');
  });
});

describe('failure', () => {
  it('turns an API error into a sentence', () => {
    expect(failure(new ApiError(404, 'no such token'))).toBe('No such token.');
    expect(failure(new ApiError(0, 'Cannot reach the server'))).toBe(
      'Cannot reach the server. Check the connection and try again.',
    );
    expect(failure(new ApiError(401, 'please sign in'))).toBe('Your session has expired. Sign in again.');
    expect(failure(new Error('boom'))).toBe('Boom.');
    expect(failure('x')).toBe('Something went wrong. Try again.');
  });

  it('explains a PIN form refusal', () => {
    expect(pinFailure(new ApiError(403, 'wrong password'))).toBe('That is not your password.');
    expect(pinFailure(new ApiError(429, 'too many'))).toBe('Too many wrong passwords. Try again in 15 minutes.');
    expect(pinFailure(new ApiError(422, 'pin: must be digits'))).toBe('Pin: must be digits.');
  });
});

describe('pinLine', () => {
  it('says since when the PIN is set', () => {
    const today = Date.UTC(2026, 9, 12, 9, 5) / 1000;
    const earlier = Date.UTC(2026, 9, 3, 15, 10) / 1000;
    expect(pinLine({ can_confirm: true, has_pin: true, pin_set_at: today }, NOW)).toBe(
      'Your PIN is set (since 09:05).',
    );
    expect(pinLine({ can_confirm: true, has_pin: true, pin_set_at: earlier }, NOW)).toBe(
      'Your PIN is set (since 3 Oct, 15:10).',
    );
  });

  it('leaves the date out for a PIN set before the server recorded it', () => {
    expect(pinLine({ can_confirm: true, has_pin: true, pin_set_at: null }, NOW)).toBe('Your PIN is set.');
    expect(pinLine({ can_confirm: true, has_pin: true }, NOW)).toBe('Your PIN is set.');
  });

  it('says when there is no PIN, or no need for one', () => {
    expect(pinLine({ can_confirm: true, has_pin: false }, NOW)).toBe('You have no PIN yet.');
    expect(pinLine({ can_confirm: false, has_pin: false }, NOW)).toBe(
      "Your role can't confirm actions, so no PIN is needed.",
    );
  });
});

describe('lockedLine', () => {
  it('names the time the lock ends', () => {
    const until = Date.UTC(2026, 9, 12, 14, 47) / 1000;
    expect(lockedLine(until)).toBe('Actions are locked until 14:47 after too many wrong PINs.');
  });
});

describe('pinHint and pinPattern', () => {
  it('follow the lengths the server allows', () => {
    expect(pinHint(4, 12)).toBe('4 to 12 digits');
    expect(pinHint(6, 6)).toBe('6 digits');
    expect(pinPattern(4, 12)).toBe('[0-9]{4,12}');
    const pattern = new RegExp(`^${pinPattern(4, 12)}$`);
    expect(pattern.test('1234')).toBe(true);
    expect(pattern.test('123')).toBe(false);
    expect(pattern.test('12a4')).toBe(false);
  });
});

describe('endedText', () => {
  it('counts the sessions that were ended', () => {
    expect(endedText(0)).toBe('No other devices were signed in.');
    expect(endedText(1)).toBe('Ended 1 other session');
    expect(endedText(2)).toBe('Ended 2 other sessions');
  });
});

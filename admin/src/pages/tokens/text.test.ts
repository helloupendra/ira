import { describe, expect, it } from 'vitest';
import { ApiError } from '../../api/client';
import { currentFirst, deviceName, endedText, failure, pinFailure, plain, plural, scopeList } from './text';

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

describe('endedText', () => {
  it('counts the sessions that were ended', () => {
    expect(endedText(0)).toBe('No other devices were signed in.');
    expect(endedText(1)).toBe('Ended 1 other session');
    expect(endedText(2)).toBe('Ended 2 other sessions');
  });
});

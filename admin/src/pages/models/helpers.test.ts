import { describe, expect, it } from 'vitest';
import { ApiError } from '../../api/client';
import { coolingLeft, coolingNote, detailOf, move, sameOrder, testLine, voiceLabel } from './helpers';

describe('move', () => {
  const chain = ['a:1', 'b:2', 'c:3'];

  it('swaps with the neighbour in that direction', () => {
    expect(move(chain, 1, -1)).toEqual(['b:2', 'a:1', 'c:3']);
    expect(move(chain, 1, 1)).toEqual(['a:1', 'c:3', 'b:2']);
  });

  it('leaves the ends where they are', () => {
    expect(move(chain, 0, -1)).toEqual(chain);
    expect(move(chain, 2, 1)).toEqual(chain);
  });

  it('never changes the list it was given', () => {
    const copy = [...chain];
    move(chain, 0, 1);
    expect(chain).toEqual(copy);
  });
});

describe('sameOrder', () => {
  it('compares item by item', () => {
    expect(sameOrder(['a', 'b'], ['a', 'b'])).toBe(true);
    expect(sameOrder(['a', 'b'], ['b', 'a'])).toBe(false);
    expect(sameOrder(['a'], ['a', 'b'])).toBe(false);
    expect(sameOrder([], [])).toBe(true);
  });
});

describe('coolingLeft', () => {
  const cooling = { 'openai:gpt': 42, 'demo:router': 0.4 };

  it('is null for a model that is not cooling', () => {
    expect(coolingLeft(cooling, 'other:quiet-model', 0)).toBeNull();
    expect(coolingLeft({}, 'openai:gpt', 0)).toBeNull();
  });

  it('counts whole seconds down and stops at zero', () => {
    expect(coolingLeft(cooling, 'openai:gpt', 0)).toBe(42);
    expect(coolingLeft(cooling, 'openai:gpt', 41.2)).toBe(1);
    expect(coolingLeft(cooling, 'openai:gpt', 42)).toBeNull();
    expect(coolingLeft(cooling, 'openai:gpt', 90)).toBeNull();
    expect(coolingLeft(cooling, 'demo:router', 0)).toBe(1);
  });

  it('treats a clock that ran backwards as no time passed', () => {
    expect(coolingLeft(cooling, 'openai:gpt', -5)).toBe(42);
  });
});

describe('coolingNote', () => {
  it('reads the kind, then the sentence', () => {
    expect(coolingNote({ error_kind: 'timeout', status: null, message: 'No answer in time.' })).toBe(
      'timeout: No answer in time.',
    );
  });

  it('shows the HTTP status once, where the server already named it', () => {
    expect(
      coolingNote({
        error_kind: 'capacity',
        status: 429,
        message: 'The provider is busy or rate-limited (HTTP 429).',
      }),
    ).toBe('capacity: The provider is busy or rate-limited (HTTP 429).');
  });

  it('adds the HTTP status before the full stop when the sentence lacks it', () => {
    expect(
      coolingNote({ error_kind: 'server', status: 503, message: 'The provider answered with an error.' }),
    ).toBe('server: The provider answered with an error (HTTP 503).');
    expect(coolingNote({ error_kind: 'auth', status: 401, message: 'Key refused' })).toBe(
      'auth: Key refused (HTTP 401)',
    );
  });

  it('copes with a missing kind or sentence', () => {
    expect(coolingNote({ error_kind: '', status: 429, message: '' })).toBe('(HTTP 429)');
    expect(coolingNote({ error_kind: 'error', status: null, message: ' ' })).toBe('error');
    expect(coolingNote({ error_kind: '', status: 0, message: 'The call failed.' })).toBe('The call failed.');
  });
});

describe('voiceLabel', () => {
  it('lists the languages, then the gender', () => {
    expect(voiceLabel({ id: 'Kajal', languages: ['en-IN', 'hi-IN'], gender: 'female' })).toBe('en-IN, hi-IN, female');
    expect(voiceLabel({ id: 'Arthur', languages: ['en-GB'], gender: 'male' })).toBe('en-GB, male');
  });

  it('is empty for a voice the provider says nothing about', () => {
    expect(voiceLabel({ id: 'alloy', languages: [], gender: null })).toBe('');
    expect(voiceLabel({ id: 'demo', languages: [' '], gender: '' })).toBe('');
  });
});

describe('testLine', () => {
  it('reads ok with the latency and the reply', () => {
    const line = testLine({ ref: 'demo:router', ok: true, seconds: 1.234, text: '  Hello. ' });
    expect(line).toEqual({ tone: 'ok', text: 'ok, 1.23 s', detail: 'Hello.' });
  });

  it('leaves out an empty reply', () => {
    expect(testLine({ ref: 'demo:router', ok: true, seconds: 0.001, text: '' }).detail).toBeNull();
    expect(testLine({ ref: 'demo:router', ok: true, seconds: 0.001 }).detail).toBeNull();
  });

  it('reads failed with the kind and the message', () => {
    const line = testLine({ ref: 'x:y', ok: false, seconds: 30, error_kind: 'timeout', error: 'took too long' });
    expect(line).toEqual({ tone: 'danger', text: 'failed: timeout took too long', detail: null });
    expect(testLine({ ref: 'x:y', ok: false, seconds: 0, error_kind: null, error: 'no key' }).text).toBe('failed: no key');
    expect(testLine({ ref: 'x:y', ok: false, seconds: 0 }).text).toBe('failed');
  });
});

describe('detailOf', () => {
  it("shows the server's sentence, else the error, else a fallback", () => {
    expect(detailOf(new ApiError(403, "your role lacks 'admin.write'"))).toBe("your role lacks 'admin.write'");
    expect(detailOf(new Error('boom'))).toBe('boom');
    expect(detailOf('what')).toBe('Something went wrong.');
  });
});

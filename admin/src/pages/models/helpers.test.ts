import { describe, expect, it } from 'vitest';
import { ApiError } from '../../api/client';
import { coolingLeft, detailOf, move, sameOrder, testLine } from './helpers';

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

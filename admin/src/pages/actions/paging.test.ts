import { describe, expect, it } from 'vitest';
import { cursorAfter, withoutRepeats } from './paging';

const a = { id: 'act_a', created_at: 300 };
const b = { id: 'act_b', created_at: 200 };
const c = { id: 'act_c', created_at: 200 };

describe('cursorAfter', () => {
  it('points at the last row shown', () => {
    expect(cursorAfter([a, b])).toEqual({ before: 200, before_id: 'act_b' });
  });
  it('has nowhere to go from an empty list', () => {
    expect(cursorAfter([])).toBeNull();
  });
});

describe('withoutRepeats', () => {
  it('drops rows already on screen', () => {
    expect(withoutRepeats([a, b], [b, c])).toEqual([c]);
    expect(withoutRepeats([], [a])).toEqual([a]);
  });
});

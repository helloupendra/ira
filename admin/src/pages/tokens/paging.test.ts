import { describe, expect, it } from 'vitest';
import { cursorAfter, newRows } from './paging';

describe('cursorAfter', () => {
  it('points at the last row by when it was last used', () => {
    const rows = [
      { id: 'ses_a', created_at: 10, last_used_at: 20 },
      { id: 'ses_b', created_at: 5, last_used_at: 15 },
    ];
    expect(cursorAfter(rows)).toEqual({ before: 15, before_id: 'ses_b' });
  });

  it('uses the sign-in time for a session never used since, as the server orders it', () => {
    expect(cursorAfter([{ id: 'ses_c', created_at: 7, last_used_at: null }])).toEqual({
      before: 7,
      before_id: 'ses_c',
    });
  });

  it('has nowhere to point with no rows', () => {
    expect(cursorAfter([])).toBeNull();
  });
});

describe('newRows', () => {
  it('drops rows already on the list', () => {
    const have = [{ id: 'a' }, { id: 'b' }];
    expect(newRows(have, [{ id: 'b' }, { id: 'c' }])).toEqual([{ id: 'c' }]);
    expect(newRows([], [{ id: 'a' }])).toEqual([{ id: 'a' }]);
    expect(newRows(have, [])).toEqual([]);
  });
});

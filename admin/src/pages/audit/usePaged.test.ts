import { describe, expect, it } from 'vitest';
import type { Page } from '../../api/client';
import { appended, visible } from './usePaged';

interface Row {
  id: number;
}

function page(ids: number[], hasMore: boolean): Page<Row[]> {
  return { rows: ids.map((id) => ({ id })), hasMore };
}

const ids = (rows: Row[]) => rows.map((row) => row.id);

describe('a paged list', () => {
  it('shows nothing before the first page arrives', () => {
    expect(visible(undefined, null)).toEqual({ rows: [], hasMore: false });
  });

  it('takes whether more follow from the page, not from its size', () => {
    expect(visible(page([3, 2, 1], true), null).hasMore).toBe(true);
    expect(visible(page([3, 2, 1], false), null).hasMore).toBe(false);
    expect(visible(page([9], true), null).hasMore).toBe(true);
  });

  it('adds each page after the first, and the last one says whether more follow', () => {
    const first = page([6, 5], true);
    const tail = appended(first, null, page([4, 3], true));
    expect(ids(visible(first, tail).rows)).toEqual([6, 5, 4, 3]);
    expect(visible(first, tail).hasMore).toBe(true);

    const end = appended(first, tail, page([2], false));
    expect(ids(visible(first, end).rows)).toEqual([6, 5, 4, 3, 2]);
    expect(visible(first, end).hasMore).toBe(false);
  });

  it('drops the pages loaded after the first once a refresh replaces it', () => {
    const first = page([6, 5], true);
    const tail = appended(first, null, page([4], false));
    const refreshed = page([7, 6, 5], true);
    expect(visible(refreshed, tail)).toEqual({ rows: refreshed.rows, hasMore: true });

    const again = appended(refreshed, tail, page([4], false));
    expect(ids(again.rows)).toEqual([4]);
    expect(again.after).toBe(refreshed);
  });

  it('never shows a row twice, and ends the list when a page brings nothing new', () => {
    const first = page([6, 5], true);
    const tail = appended(first, null, page([5, 4], true));
    expect(ids(tail.rows)).toEqual([4]);
    expect(tail.hasMore).toBe(true);

    const stuck = appended(first, tail, page([4], true));
    expect(ids(stuck.rows)).toEqual([4]);
    expect(stuck.hasMore).toBe(false);
  });
});

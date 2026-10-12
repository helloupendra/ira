import { useEffect, useRef, useState, type DependencyList } from 'react';
import type { Page } from '../../api/client';
import { useApi, type ApiState } from '../../ui/useApi';

// The pages loaded after the first, kept with the first page they follow: a
// refresh replaces that page, and these are dropped with it.
export interface Tail<T> {
  after: Page<T[]>;
  rows: T[];
  hasMore: boolean;
}

export interface Paged<T> {
  // The first page: its loading, error and reload stand for the whole list.
  first: ApiState<Page<T[]>>;
  rows: T[];
  hasMore: boolean;
  loadingMore: boolean;
  moreError: Error | null;
  loadMore: () => void;
}

// What the list shows: the first page and, while the tail still follows it,
// the pages loaded after. Whether more follow is what the server said about
// the last page fetched.
export function visible<T>(first: Page<T[]> | undefined, tail: Tail<T> | null): { rows: T[]; hasMore: boolean } {
  if (!first) return { rows: [], hasMore: false };
  if (tail && tail.after === first) return { rows: [...first.rows, ...tail.rows], hasMore: tail.hasMore };
  return { rows: first.rows, hasMore: first.hasMore };
}

// The tail with one more page on it. A row already shown is not shown twice,
// and a page that brings nothing new ends the list: the cursor could not move
// on from it.
export function appended<T extends { id: number }>(first: Page<T[]>, prev: Tail<T> | null, page: Page<T[]>): Tail<T> {
  const kept = prev && prev.after === first ? prev.rows : [];
  const seen = new Set([...first.rows, ...kept].map((row) => row.id));
  const fresh = page.rows.filter((row) => !seen.has(row.id));
  return { after: first, rows: [...kept, ...fresh], hasMore: page.hasMore && fresh.length > 0 };
}

// A newest-first list the server pages by id ("only rows older than this
// id"), each page saying whether more follow it.
export function usePaged<T extends { id: number }>(
  fetchPage: (beforeId: number | null, signal: AbortSignal) => Promise<Page<T[]>>,
  deps: DependencyList,
): Paged<T> {
  const first = useApi((signal) => fetchPage(null, signal), deps);
  const [tail, setTail] = useState<Tail<T> | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState<Error | null>(null);
  const inFlight = useRef<AbortController | null>(null);

  useEffect(() => () => inFlight.current?.abort(), []);

  const base = first.data;
  const { rows, hasMore } = visible(base, tail);

  async function loadMore() {
    const last = rows[rows.length - 1];
    if (!base || !last || loadingMore) return;
    const controller = new AbortController();
    inFlight.current = controller;
    setLoadingMore(true);
    setMoreError(null);
    try {
      const page = await fetchPage(last.id, controller.signal);
      if (controller.signal.aborted) return;
      setTail((prev) => appended(base, prev, page));
    } catch (err) {
      if (controller.signal.aborted) return;
      setMoreError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      if (!controller.signal.aborted) setLoadingMore(false);
    }
  }

  return { first, rows, hasMore, loadingMore, moreError, loadMore: () => void loadMore() };
}

import { useEffect, useRef, useState, type DependencyList } from 'react';
import type { Page } from '../../api/client';
import { useApi, type ApiState } from '../../ui/useApi';
import { newRows } from './paging';

// The pages after the first, kept with the first page they follow: a reload
// replaces that page and drops these with it.
interface Tail<T> {
  after: Page<T[]>;
  rows: T[];
  hasMore: boolean;
}

export interface PagedList<T> {
  // Every row loaded so far. The first page's loading, error and reload
  // stand for the whole list.
  state: ApiState<T[]>;
  hasMore: boolean;
  loadingMore: boolean;
  moreError: Error | null;
  loadMore: () => void;
}

// A list the server pages with a cursor read from the last row. Each answer
// says whether more rows follow (X-Has-More), so the end is never guessed.
export function usePagedList<T extends { id: string }, C>(
  fetchPage: (cursor: C | null, signal: AbortSignal) => Promise<Page<T[]>>,
  cursorAfter: (rows: readonly T[]) => C | null,
  deps: DependencyList,
): PagedList<T> {
  const first = useApi((signal) => fetchPage(null, signal), deps);
  const [tail, setTail] = useState<Tail<T> | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState<Error | null>(null);
  const inFlight = useRef<AbortController | null>(null);

  useEffect(() => () => inFlight.current?.abort(), []);

  const page = first.data;
  const extra = tail && page && tail.after === page ? tail : null;
  const rows = page ? (extra ? [...page.rows, ...extra.rows] : page.rows) : undefined;
  const hasMore = extra ? extra.hasMore : (page?.hasMore ?? false);

  async function loadMore() {
    if (!page || !rows || loadingMore) return;
    const cursor = cursorAfter(rows);
    if (!cursor) return;
    const controller = new AbortController();
    inFlight.current = controller;
    setLoadingMore(true);
    setMoreError(null);
    try {
      const next = await fetchPage(cursor, controller.signal);
      if (controller.signal.aborted) return;
      setTail((prev) => {
        const kept = prev && prev.after === page ? prev.rows : [];
        return {
          after: page,
          rows: [...kept, ...newRows([...page.rows, ...kept], next.rows)],
          hasMore: next.hasMore,
        };
      });
    } catch (err) {
      if (controller.signal.aborted) return;
      setMoreError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      if (!controller.signal.aborted) setLoadingMore(false);
    }
  }

  return {
    state: { data: rows, error: first.error, loading: first.loading, reload: first.reload },
    hasMore,
    loadingMore,
    moreError,
    loadMore: () => void loadMore(),
  };
}

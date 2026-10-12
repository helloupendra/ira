import { useEffect, useRef, useState } from 'react';
import type { ApiError } from '../../api/client';
import type { Page } from '../../api/endpoints';
import { useApi } from '../../ui/useApi';
import { cursorAfter, withoutRepeats, type Cursor } from './paging';

// The first page, tagged with the filter it was fetched for, so the rows of
// the previous chip are never shown under the next one while it loads.
interface First<T> {
  key: string;
  rows: T[];
  hasMore: boolean;
}

// The pages loaded after the first, kept with the first page they follow: a
// refresh or a new filter replaces that page, and these go with it.
interface Tail<T> {
  after: First<T>;
  rows: T[];
  hasMore: boolean;
}

export interface Paged<T> {
  // The rows for the current key, or undefined until its first page is here.
  rows: T[] | undefined;
  // The first page's state. reload() fetches it again and drops the rest.
  loading: boolean;
  error: ApiError | null;
  reload: () => void;
  // Whether the server has rows after the last page, from its header.
  hasMore: boolean;
  loadingMore: boolean;
  moreError: Error | null;
  loadMore: () => void;
}

// A newest-first list the server pages by a cursor taken from the last row
// shown. The key is the filter the list depends on; changing it starts over.
export function usePaged<T extends { id: string; created_at: number }>(
  fetchPage: (cursor: Cursor | null, signal: AbortSignal) => Promise<Page<T[]>>,
  key: string,
): Paged<T> {
  const first = useApi<First<T>>(async (signal) => {
    const page = await fetchPage(null, signal);
    return { key, rows: page.rows, hasMore: page.hasMore };
  }, [key]);
  const [tail, setTail] = useState<Tail<T> | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState<Error | null>(null);
  const inFlight = useRef<AbortController | null>(null);

  const base = first.data && first.data.key === key ? first.data : undefined;
  const extra = tail && base && tail.after === base ? tail : null;
  const rows = base ? (extra ? [...base.rows, ...extra.rows] : base.rows) : undefined;
  const hasMore = extra ? extra.hasMore : (base?.hasMore ?? false);

  // A new first page makes a next page still on its way stale: drop it.
  useEffect(
    () => () => {
      inFlight.current?.abort();
      inFlight.current = null;
      setLoadingMore(false);
      setMoreError(null);
    },
    [base],
  );

  async function loadMore() {
    const cursor = rows ? cursorAfter(rows) : null;
    if (!base || !cursor || loadingMore) return;
    const controller = new AbortController();
    inFlight.current = controller;
    setLoadingMore(true);
    setMoreError(null);
    try {
      const page = await fetchPage(cursor, controller.signal);
      if (controller.signal.aborted) return;
      setTail((prev) => {
        const kept = prev && prev.after === base ? prev.rows : [];
        const fresh = withoutRepeats([...base.rows, ...kept], page.rows);
        return { after: base, rows: [...kept, ...fresh], hasMore: page.hasMore };
      });
    } catch (err) {
      if (controller.signal.aborted) return;
      setMoreError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      if (!controller.signal.aborted) setLoadingMore(false);
    }
  }

  return {
    rows,
    loading: first.loading,
    error: first.error,
    reload: first.reload,
    hasMore,
    loadingMore,
    moreError,
    loadMore: () => void loadMore(),
  };
}

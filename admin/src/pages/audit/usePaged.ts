import { useEffect, useRef, useState, type DependencyList } from 'react';
import { useApi, type ApiState } from '../../ui/useApi';

// The pages loaded after the first, kept with the first page they follow: a
// refresh replaces that page, and these are dropped with it.
interface Tail<T> {
  after: T[];
  rows: T[];
  lastSize: number;
}

export interface Paged<T> {
  // The first page: its loading, error and reload stand for the whole list.
  first: ApiState<T[]>;
  rows: T[];
  hasMore: boolean;
  loadingMore: boolean;
  moreError: Error | null;
  loadMore: () => void;
}

// A newest-first list the server pages by id ("only rows older than this
// id"). The page size decides whether there may be more: a short page is the
// end of the list.
export function usePaged<T extends { id: number }>(
  fetchPage: (beforeId: number | null, signal: AbortSignal) => Promise<T[]>,
  pageSize: number,
  deps: DependencyList,
): Paged<T> {
  const first = useApi((signal) => fetchPage(null, signal), deps);
  const [tail, setTail] = useState<Tail<T> | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState<Error | null>(null);
  const inFlight = useRef<AbortController | null>(null);

  useEffect(() => () => inFlight.current?.abort(), []);

  const base = first.data;
  const extra = tail && base && tail.after === base ? tail : null;
  const rows = base ? (extra ? [...base, ...extra.rows] : base) : [];
  const lastSize = extra ? extra.lastSize : (base?.length ?? 0);
  const hasMore = lastSize >= pageSize;

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
      setTail((prev) => {
        const kept = prev && prev.after === base ? prev.rows : [];
        const seen = new Set([...base, ...kept].map((row) => row.id));
        return { after: base, rows: [...kept, ...page.filter((row) => !seen.has(row.id))], lastSize: page.length };
      });
    } catch (err) {
      if (controller.signal.aborted) return;
      setMoreError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      if (!controller.signal.aborted) setLoadingMore(false);
    }
  }

  return { first, rows, hasMore, loadingMore, moreError, loadMore: () => void loadMore() };
}

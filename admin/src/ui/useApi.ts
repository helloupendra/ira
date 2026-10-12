import { useCallback, useEffect, useState, type DependencyList } from 'react';
import { ApiError } from '../api/client';

export interface ApiState<T> {
  data: T | undefined;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
}

// Runs a request when the deps change or reload() is called. The previous
// data stays on screen while a reload is in flight, and a request that is
// still running when the component unmounts is aborted and ignored.
export function useApi<T>(fn: (signal: AbortSignal) => Promise<T>, deps: DependencyList): ApiState<T> {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    fn(controller.signal).then(
      (result) => {
        if (controller.signal.aborted) return;
        setData(result);
        setError(null);
        setLoading(false);
      },
      (err: unknown) => {
        if (controller.signal.aborted) return;
        setError(err instanceof ApiError ? err : new ApiError(0, err instanceof Error ? err.message : String(err)));
        setLoading(false);
      },
    );
    return () => controller.abort();
    // The caller lists what the request depends on, like useEffect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);

  return { data, error, loading, reload };
}

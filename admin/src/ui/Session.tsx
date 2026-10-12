import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { ApiError, UNAUTHORIZED_EVENT } from '../api/client';
import { auth, type Session } from '../api/endpoints';
import { can as hasPermission, type Permission } from '../lib/roles';

// "error" covers the one case the three usual states cannot: the server could
// not be reached at all, so the console cannot even tell if you are signed in.
export type SessionStatus = 'loading' | 'anonymous' | 'ready' | 'error';

export interface SessionValue {
  status: SessionStatus;
  me: Session | null;
  error: ApiError | null;
  can(p: Permission): boolean;
  refresh(): Promise<void>;
  signOut(): Promise<void>;
}

interface State {
  status: SessionStatus;
  me: Session | null;
  error: ApiError | null;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ status: 'loading', me: null, error: null });

  const refresh = useCallback(async () => {
    try {
      const me = await auth.me();
      setState({ status: 'ready', me, error: null });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setState({ status: 'anonymous', me: null, error: null });
      } else {
        const error = err instanceof ApiError ? err : new ApiError(0, 'Cannot reach the server');
        setState({ status: 'error', me: null, error });
      }
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const onUnauthorized = () => setState({ status: 'anonymous', me: null, error: null });
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  const signOut = useCallback(async () => {
    try {
      await auth.logout();
    } catch (err) {
      // A session that is already gone counts as signed out.
      if (!(err instanceof ApiError && err.status === 401)) throw err;
    }
    setState({ status: 'anonymous', me: null, error: null });
  }, []);

  const value = useMemo<SessionValue>(
    () => ({
      status: state.status,
      me: state.me,
      error: state.error,
      can: (p) => hasPermission(state.me?.permissions, p),
      refresh,
      signOut,
    }),
    [state, refresh, signOut],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error('useSession needs a SessionProvider above it');
  return value;
}

export function useOptionalSession(): SessionValue | null {
  return useContext(SessionContext);
}

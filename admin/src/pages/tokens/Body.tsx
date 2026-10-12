import type { ReactNode } from 'react';
import type { Permission } from '../../lib/roles';
import { ErrorState, Loading, sentenceFor } from '../../ui/states';
import type { ApiState } from '../../ui/useApi';

// Shows the data when there is any, with a quiet line when a refresh failed;
// otherwise the loading or error state for that request alone, so one slow
// or failing request never blanks the whole screen.
export function Body<T>({
  state,
  needs,
  children,
}: {
  state: ApiState<T>;
  needs?: Permission;
  children: (data: T) => ReactNode;
}) {
  if (state.data === undefined) {
    if (state.error) return <ErrorState error={state.error} onRetry={state.reload} needs={needs} />;
    return <Loading />;
  }
  return (
    <>
      {state.error && (
        <p className="error-line" role="alert">
          Couldn't refresh. {sentenceFor(state.error)}
        </p>
      )}
      {children(state.data)}
    </>
  );
}

import { ApiError } from '../api/client';
import { whyNot, type Permission } from '../lib/roles';
import { useOptionalSession } from './Session';

export function Loading({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="skeleton" role="status" aria-busy="true" aria-label={label}>
      <span className="skeleton-bar" />
      <span className="skeleton-bar" />
      <span className="skeleton-bar" />
    </div>
  );
}

export function Forbidden({ why }: { why?: string }) {
  return (
    <div className="forbidden" role="status">
      <p className="forbidden-title">Not available to your role</p>
      <p className="muted">{why ?? "Your role can't do this."}</p>
    </div>
  );
}

// One sentence for an ApiError, in words a non-technical owner can act on.
export function sentenceFor(error: Error): string {
  if (!(error instanceof ApiError)) return error.message || 'Something went wrong.';
  if (error.status === 0) return 'Cannot reach the server. Check the connection and try again.';
  if (error.status === 401) return 'Your session has expired. Sign in again.';
  if (error.status === 429) return 'Too many requests. Wait a moment and try again.';
  return `Couldn't load this. ${error.detail}`;
}

export function ErrorState({
  error,
  onRetry,
  needs,
}: {
  error: Error;
  onRetry?: () => void;
  needs?: Permission;
}) {
  const session = useOptionalSession();
  if (error instanceof ApiError && error.status === 403) {
    const role = session?.me?.user.role;
    return <Forbidden why={needs && role ? whyNot(role, needs) : error.detail} />;
  }
  return (
    <div className="error-state" role="alert">
      <p>{sentenceFor(error)}</p>
      {onRetry && (
        <button type="button" className="btn btn-small" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function Empty({ title, text }: { title?: string; text: string }) {
  return (
    <div className="empty">
      {title && <p className="empty-title">{title}</p>}
      <p>{text}</p>
    </div>
  );
}

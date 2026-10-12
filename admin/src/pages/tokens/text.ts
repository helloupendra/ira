import { ApiError } from '../../api/client';

// A user agent as a short device name. Sixty characters are enough to tell a
// phone from a laptop; the whole string goes in a title for anyone curious.
export function deviceName(userAgent: string | null | undefined, max = 60): string {
  const text = (userAgent ?? '').trim();
  if (!text) return 'unknown';
  if (text.length <= max) return text;
  return `${text.slice(0, max).trimEnd()}…`;
}

// Scopes as the API sends them: comma text on a row, a list on a new token.
export function scopeList(scopes: string | readonly string[]): string {
  const parts = typeof scopes === 'string' ? scopes.split(',') : scopes;
  return parts
    .map((s) => s.trim())
    .filter(Boolean)
    .join(', ');
}

// The session making this request first, the rest in the server's order.
export function currentFirst<T extends { current: boolean }>(rows: readonly T[]): T[] {
  return [...rows].sort((a, b) => Number(b.current) - Number(a.current));
}

// A number from the config as a person writes it: 15, not 15.0; 2.5 stays.
export function plain(n: number): string {
  return String(Math.round(n * 100) / 100);
}

export function plural(n: number, word: string): string {
  return `${plain(n)} ${word}${n === 1 ? '' : 's'}`;
}

function sentence(text: string): string {
  const t = text.trim();
  if (!t) return '';
  const capital = t.charAt(0).toUpperCase() + t.slice(1);
  return /[.!?]$/.test(capital) ? capital : `${capital}.`;
}

// One sentence for a write that failed.
export function failure(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 0) return 'Cannot reach the server. Check the connection and try again.';
    if (err.status === 401) return 'Your session has expired. Sign in again.';
    if (err.status === 429) return 'Too many requests. Wait a moment and try again.';
    return sentence(err.detail) || 'Something went wrong. Try again.';
  }
  if (err instanceof Error && err.message) return sentence(err.message);
  return 'Something went wrong. Try again.';
}

// The PIN form checks the password again, so its refusals are about that.
export function pinFailure(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 403) return 'That is not your password.';
    if (err.status === 429) return 'Too many wrong passwords. Try again in 15 minutes.';
  }
  return failure(err);
}

// What a scope lets a token do, for the person ticking it.
export function scopeHint(scope: string): string | null {
  switch (scope) {
    case 'ask':
      return 'ask Ira questions';
    case 'voice':
      return 'talk to Ira by voice';
    case 'actions':
      return 'propose and confirm actions';
    case 'admin.read':
      return 'read the console';
    case 'admin.write':
      return 'change settings in the console';
    case 'users':
      return 'manage people';
    default:
      return null;
  }
}

export function endedText(n: number): string {
  if (n === 0) return 'No other devices were signed in.';
  return `Ended ${n} other ${n === 1 ? 'session' : 'sessions'}`;
}

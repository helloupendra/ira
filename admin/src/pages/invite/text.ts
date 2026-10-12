import { ApiError } from '../../api/client';

export const MIN_PASSWORD = 10;

export const MISSING = 'This link is missing its invitation code. Ask the person who invited you for the full link.';
export const GONE = "This invitation isn't valid any more: it was used, withdrawn or it expired. Ask for a new one.";
export const TOO_SHORT = `Use at least ${MIN_PASSWORD} characters.`;
export const NO_MATCH = "The passwords don't match.";

// The code rides in the fragment (/admin/invite#token=ira_i_...), so it never
// reaches a server log as part of the address.
export function tokenFrom(hash: string): string | null {
  const token = new URLSearchParams(hash.replace(/^#/, '')).get('token')?.trim();
  return token ? token : null;
}

// What the role lets the person do, in one line.
export function roleLine(role: string): string | null {
  switch (role) {
    case 'owner':
      return 'An owner can do everything, including managing users.';
    case 'admin':
      return 'An admin can do everything except managing users.';
    case 'staff':
      return 'Staff talk to Ira and confirm actions with their own PIN.';
    case 'viewer':
      return 'A viewer reads the console and cannot change anything.';
    default:
      return null;
  }
}

export interface Problems {
  password?: string;
  confirm?: string;
}

// The checks the form makes before asking the server.
export function passwordProblems(password: string, confirm: string): Problems {
  const problems: Problems = {};
  if (password.length < MIN_PASSWORD) problems.password = TOO_SHORT;
  if (confirm !== password) problems.confirm = NO_MATCH;
  return problems;
}

// An invitation that was used, withdrawn or expired, from lookup or accept.
export function isGone(err: unknown): boolean {
  return err instanceof ApiError && err.status === 410;
}

// "the password must be at least 10 characters" reads as a sentence.
function sentence(text: string): string {
  const t = text.trim();
  if (!t) return '';
  const capital = t.charAt(0).toUpperCase() + t.slice(1);
  return /[.!?]$/.test(capital) ? capital : `${capital}.`;
}

// One sentence for an accept that failed; a gone invitation is a state of
// its own, so it is handled before this.
export function failure(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 0) return 'Cannot reach the server. Check the connection and try again.';
    if (err.status === 429) return 'Too many tries. Wait a moment and try again.';
    return sentence(err.detail) || 'Something went wrong. Try again.';
  }
  return 'Something went wrong. Try again.';
}

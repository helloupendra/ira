import { ApiError } from '../../api/client';
import type { AdminUserRow, InviteView, RoleView } from '../../api/endpoints';
import { ago } from '../../lib/format';

// The roles a person can hold, in the order the console lists them.
export const ROLES = ['owner', 'admin', 'staff', 'viewer'] as const;

export const LAST_OWNER = "The last owner can't be removed or demoted. Make someone else owner first.";
export const SELF_REMOVE = "You can't remove yourself.";
export const NO_PIN = 'No PIN to clear.';

export function ownerCount(users: readonly AdminUserRow[]): number {
  return users.filter((user) => user.role === 'owner').length;
}

export function isLastOwner(user: AdminUserRow, users: readonly AdminUserRow[]): boolean {
  return user.role === 'owner' && ownerCount(users) === 1;
}

// Why the role select is disabled for this person, or null when it is not.
export function roleReason(user: AdminUserRow, users: readonly AdminUserRow[]): string | null {
  return isLastOwner(user, users) ? LAST_OWNER : null;
}

// Why Remove is disabled for this person, or null when it is not. The last
// owner's reason covers the role select too, so it is the line under the row.
export function removeReason(
  user: AdminUserRow,
  users: readonly AdminUserRow[],
  meId: number | undefined,
): string | null {
  if (isLastOwner(user, users)) return LAST_OWNER;
  if (user.id === meId) return SELF_REMOVE;
  return null;
}

// Why Reset PIN is disabled, or null: there is nothing to clear without a PIN.
export function pinReason(user: AdminUserRow): string | null {
  return user.has_pin ? null : NO_PIN;
}

export function lastSignIn(user: AdminUserRow, now?: number): string {
  if (user.last_login_at === null || user.last_login_at === undefined) return 'never';
  return ago(user.last_login_at, now);
}

// For a card, where no column header says what the time is.
export function signInSentence(user: AdminUserRow, now?: number): string {
  const text = lastSignIn(user, now);
  return text === 'never' ? 'Never signed in' : `Signed in ${text}`;
}

// The link to send. The server gives a path on its own origin.
export function inviteLink(origin: string, path: string): string {
  return path.startsWith('/') ? origin + path : `${origin}/${path}`;
}

// Only a pending invitation can still be accepted or withdrawn.
export function isOpen(invite: InviteView): boolean {
  return invite.state === 'pending';
}

function rank(role: string): number {
  const i = (ROLES as readonly string[]).indexOf(role);
  return i === -1 ? ROLES.length : i;
}

export function sortRoles(roles: readonly RoleView[]): RoleView[] {
  return [...roles].sort((a, b) => rank(a.role) - rank(b.role) || a.role.localeCompare(b.role));
}

export function permissionsText(role: RoleView): string {
  return role.permissions.join(', ');
}

// "the last owner cannot be removed" reads as "The last owner cannot be removed."
function sentence(text: string): string {
  const capitalised = text.charAt(0).toUpperCase() + text.slice(1);
  return /[.!?]$/.test(capitalised) ? capitalised : `${capitalised}.`;
}

// What a failed write says: the server's own detail when there is one.
export function failureText(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 0) return 'Cannot reach the server. Check the connection and try again.';
    return sentence(err.detail);
  }
  return 'Something went wrong. Try again.';
}

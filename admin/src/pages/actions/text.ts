import type { ActionRow, ToolDetail } from '../../api/endpoints';
import { clock, humanize, when } from '../../lib/format';

// The chips in the order they are shown. The value is the status query
// parameter; the empty string is "All".
export const FILTERS: readonly { value: string; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'pending', label: 'Pending' },
  { value: 'executed', label: 'Executed' },
  { value: 'failed', label: 'Failed' },
  { value: 'expired', label: 'Expired' },
  { value: 'cancelled', label: 'Cancelled' },
];

// The status named in the query string, or '' for all of them.
export function statusFromSearch(search: string): string {
  return new URLSearchParams(search).get('status')?.trim() ?? '';
}

export function hrefFor(status: string): string {
  return status ? `/actions?status=${encodeURIComponent(status)}` : '/actions';
}

// A chip label for a status the Overview linked to that has no chip of its
// own, such as "executing".
export function labelFor(status: string): string {
  const words = humanize(status);
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function emptyText(status: string): string {
  switch (status) {
    case '':
      return 'No actions yet. When Ira proposes a change it appears here with its outcome.';
    case 'pending':
      return 'No pending actions.';
    case 'executed':
      return 'No executed actions yet.';
    case 'failed':
      return 'No failed actions.';
    case 'expired':
      return 'No expired actions.';
    case 'cancelled':
      return 'No cancelled actions.';
    default:
      return `No ${humanize(status)} actions.`;
  }
}

// The server already writes the actor as "owner@example.com via web", so the
// channel is added only when the actor does not name it.
export function proposedBy(actor: string | null | undefined, channel: string | null | undefined): string {
  const who = actor?.trim() ?? '';
  const via = channel?.trim() ?? '';
  if (!who && !via) return 'not recorded';
  if (!who) return `someone via ${via}`;
  if (!via || who.toLowerCase().includes(`via ${via.toLowerCase()}`)) return who;
  return `${who} via ${via}`;
}

// "owner, admin or staff"
export function listRoles(roles: readonly string[]): string {
  if (roles.length <= 1) return roles.join('');
  return `${roles.slice(0, -1).join(', ')} or ${roles[roles.length - 1]}`;
}

// Read-only: the roles come from ira.yaml and cannot be changed here.
export function whoMayConfirm(tool: ToolDetail | undefined): string {
  if (!tool) return 'the tool is no longer registered';
  const roles = tool.confirm_roles;
  if (roles === null || roles === undefined) return 'no one: the tool no longer asks for confirmation';
  if (roles.length === 0) return 'no one (no roles are set in ira.yaml)';
  return `${listRoles(roles)} (set in ira.yaml)`;
}

export interface OutcomeLine {
  label: string;
  text: string;
  // A word after the text, shown quietly: "expired" on a pending action
  // whose time has run out.
  note?: string;
}

// The line that says where the action stands: when a pending one runs out,
// or who decided one that is done.
export function outcomeLine(row: ActionRow, now: number): OutcomeLine | null {
  if (row.status === 'pending') {
    const passed = row.expires_at <= now;
    return passed
      ? { label: 'Expired at', text: clock(row.expires_at), note: 'expired' }
      : { label: 'Expires at', text: clock(row.expires_at) };
  }
  if (row.status === 'expired') {
    return { label: 'Expired at', text: when(row.expires_at, now) };
  }
  const by = row.decided_by?.trim() ?? '';
  const at = row.decided_at ?? null;
  if (by && at !== null) return { label: 'Decided by', text: `${by} at ${when(at, now)}` };
  if (by) return { label: 'Decided by', text: by };
  if (at !== null) return { label: 'Decided at', text: when(at, now) };
  if (row.finished_at !== null) return { label: 'Finished at', text: when(row.finished_at, now) };
  return null;
}

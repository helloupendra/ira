import type { ActionCounts, ActionRow, ToolDetail } from '../../api/endpoints';
import { clock, humanize, when } from '../../lib/format';

// The chips in the order they are shown. The value is the status query
// parameter; the empty string is "All".
export const FILTERS: readonly { value: string; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'pending', label: 'Pending' },
  { value: 'executed', label: 'Executed' },
  { value: 'failed', label: 'Failed' },
  { value: 'unknown', label: 'Unknown' },
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

// The number on a chip: every action for "All", otherwise those in that
// status. Null until the counts arrive, and for a status the server does
// not count.
export function countFor(counts: ActionCounts | undefined, status: string): number | null {
  if (!counts) return null;
  switch (status) {
    case '':
      return counts.total;
    case 'pending':
      return counts.pending;
    case 'executing':
      return counts.executing;
    case 'executed':
      return counts.executed;
    case 'failed':
      return counts.failed;
    case 'unknown':
      return counts.unknown ?? 0;
    case 'expired':
      return counts.expired;
    case 'cancelled':
      return counts.cancelled;
    default:
      return null;
  }
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
    case 'unknown':
      return 'No actions of unknown outcome: none ran out of time or was cut off by a restart.';
    case 'expired':
      return 'No expired actions.';
    case 'cancelled':
      return 'No cancelled actions.';
    default:
      return `No ${humanize(status)} actions.`;
  }
}

// "owner@example.com via web": the person, then the channel they used. The
// server keeps the two apart, so neither is looked for in the other.
export function proposedBy(actor: string | null | undefined, channel: string | null | undefined): string {
  const who = actor?.trim() ?? '';
  const via = channel?.trim() ?? '';
  if (who && via) return `${who} via ${via}`;
  if (who) return who;
  if (via) return `someone via ${via}`;
  return 'not recorded';
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
}

// The line that says where the action stands: when a pending one runs out
// (the server marks it expired once that time has passed, so the list never
// has to say so itself), when an expired one ran out, or who decided one
// that is done, and where.
export function outcomeLine(row: ActionRow, now: number = Date.now() / 1000): OutcomeLine | null {
  if (row.status === 'pending') return { label: 'Expires at', text: clock(row.expires_at) };
  if (row.status === 'expired') return { label: 'Expired at', text: when(row.expires_at, now) };
  const by = row.decided_by?.trim() ?? '';
  const via = row.decided_channel?.trim() ?? '';
  const at = row.decided_at === null || row.decided_at === undefined ? '' : when(row.decided_at, now);
  const rest = [via && `via ${via}`, at && `at ${at}`].filter(Boolean).join(' ');
  if (by) return { label: 'Decided by', text: rest ? `${by} ${rest}` : by };
  if (via) return { label: 'Decided', text: rest };
  if (at) return { label: 'Decided at', text: at };
  if (row.finished_at !== null) return { label: 'Finished at', text: when(row.finished_at, now) };
  return null;
}

import { ApiError } from '../../api/client';
import { humanize } from '../../lib/format';

// The colour of a tool's kind: reads are quiet, actions stand out a little.
export function kindBadge(kind: string): string {
  switch (kind) {
    case 'read':
      return 'badge badge-accent';
    case 'action':
      return 'badge badge-warn';
    default:
      return 'badge badge-muted';
  }
}

// ["owner", "admin", "staff"] reads as "owner, admin or staff".
export function listed(items: readonly string[]): string {
  if (items.length <= 1) return items.join('');
  return `${items.slice(0, -1).join(', ')} or ${items[items.length - 1]}`;
}

// The sentence shown after a tool is switched. Off is the one to spell out:
// the owner should know Ira stops seeing the tool.
export function switchedToast(name: string, enabled: boolean): string {
  const label = humanize(name);
  return enabled ? `${label} is on.` : `${label} is off. Ira won't see it until it is on again.`;
}

// What went wrong with a write, in a sentence for people.
export function failure(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 0) return 'Cannot reach the server. Check the connection and try again.';
    return err.detail;
  }
  return err instanceof Error && err.message ? err.message : 'Something went wrong.';
}

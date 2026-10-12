import type { CallRow, CostDay } from '../../api/endpoints';
import { humanize } from '../../lib/format';

export type View = 'changes' | 'actions' | 'cost';

// The chips in the order they are shown. The value is the view query
// parameter; "changes" is the default and has no parameter of its own.
export const VIEWS: readonly { value: View; label: string }[] = [
  { value: 'changes', label: 'Changes' },
  { value: 'actions', label: 'Actions' },
  { value: 'cost', label: 'Cost' },
];

export function viewFromSearch(search: string): View {
  const raw = new URLSearchParams(search).get('view')?.trim().toLowerCase() ?? '';
  const known = VIEWS.find((v) => v.value === raw);
  return known ? known.value : 'changes';
}

export function hrefFor(view: View): string {
  return view === 'changes' ? '/audit' : `/audit?view=${view}`;
}

// A change code as words: "tool.enabled" reads as "tool enabled",
// "user.invite_withdrawn" as "user invite withdrawn".
export function changeWords(what: string): string {
  return humanize(what.replace(/\./g, ' '));
}

// A day the server reports as "YYYY-MM-DD", as midnight local time in
// seconds, for dayDate(). Null when the string is not a real date.
export function dayEpoch(day: string): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day.trim());
  if (!m) return null;
  const y = Number(m[1]);
  const mo = Number(m[2]);
  const d = Number(m[3]);
  const date = new Date(y, mo - 1, d);
  if (date.getFullYear() !== y || date.getMonth() !== mo - 1 || date.getDate() !== d) return null;
  return date.getTime() / 1000;
}

// Newest day first, whichever way the server sent them.
export function byDayDesc(rows: readonly CostDay[]): CostDay[] {
  return [...rows].sort((a, b) => (a.day < b.day ? 1 : a.day > b.day ? -1 : 0));
}

export interface Totals {
  calls: number;
  failures: number;
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
}

export function totals(rows: readonly CostDay[]): Totals {
  const sum: Totals = { calls: 0, failures: 0, cost_usd: 0, input_tokens: 0, output_tokens: 0 };
  for (const row of rows) {
    sum.calls += row.calls;
    sum.failures += row.failures;
    sum.cost_usd += row.cost_usd;
    sum.input_tokens += row.input_tokens;
    sum.output_tokens += row.output_tokens;
  }
  return sum;
}

// The word in the OK column: "ok", or what went wrong.
export function okLabel(row: Pick<CallRow, 'ok' | 'error_kind'>): string {
  if (row.ok) return 'ok';
  const kind = row.error_kind?.trim();
  return kind ? humanize(kind) : 'failed';
}

// The models a call went through, when it took more than one attempt:
// "tried: openai:gpt-4o-mini, demo:router (2 attempts)". Null otherwise.
export function triedLine(row: Pick<CallRow, 'tried' | 'attempts' | 'model'>): string | null {
  if (row.attempts <= 1) return null;
  const models = row.tried
    .split(/[,\s]+/)
    .map((s) => s.trim())
    .filter(Boolean);
  const list = models.length ? models.join(', ') : (row.model ?? 'none');
  return `tried: ${list} (${row.attempts} attempts)`;
}

// Who did it and where, in one line. The server usually writes the actor as
// "owner@example.com via web", so the channel is added only when the actor
// does not already name it.
export function viaLine(actor: string | null | undefined, channel: string | null | undefined): string {
  const who = actor?.trim() ?? '';
  const via = channel?.trim() ?? '';
  if (!who && !via) return 'not recorded';
  if (!who) return `someone via ${via}`;
  if (!via || who.toLowerCase().includes(`via ${via.toLowerCase()}`)) return who;
  return `${who} via ${via}`;
}

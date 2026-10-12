import type { MessageRow } from '../../api/endpoints';
import { clock, count, when } from '../../lib/format';

// The action a tool call proposed, as it stands now.
export type MessageAction = NonNullable<MessageRow['action']>;

// A conversation's id goes in the path, and ids carry colons ("web:1:bd69..."),
// so the href encodes it. wouter hands the param back exactly as it appears in
// the URL, so the page decodes it again.
export function hrefOf(id: string): string {
  return `/conversations/${encodeURIComponent(id)}`;
}

export function idFromParam(param: string): string {
  try {
    return decodeURIComponent(param);
  } catch {
    return param;
  }
}

// Where the Actions screen lists the proposals in one state.
export function actionsHref(status: string): string {
  return status ? `/actions?status=${encodeURIComponent(status)}` : '/actions';
}

// Turns are the questions asked, which is how the list counts them.
export function turnsLabel(n: number): string {
  return `${count(n)} ${n === 1 ? 'turn' : 'turns'}`;
}

// Whose conversation it is: the account, or the channel when nobody signed in.
export function whoOf(row: { email: string | null; channel: string }): string {
  return row.email ?? row.channel;
}

export function whoLabel(role: string): string {
  if (role === 'user') return 'User';
  if (role === 'assistant') return 'Ira';
  return role ? role.charAt(0).toUpperCase() + role.slice(1) : 'Unknown';
}

// One line of at most `max` characters, the ellipsis included.
export function cut(text: string, max: number): string {
  const line = text.replace(/\s+/g, ' ').trim();
  const chars = Array.from(line);
  if (chars.length <= max) return line;
  return `${chars.slice(0, max - 1).join('').trimEnd()}…`;
}

// A conversation is named after the first thing the user said, or its id when
// nothing was said.
export function titleOf(row: { id: string; preview?: string | null }): string {
  const preview = row.preview?.trim() ?? '';
  return preview ? cut(preview, 80) : row.id;
}

// The line under the title: "owner@example.com, 2 turns, started 15:55, last
// 15:57". The channel is a badge in front of it, so a conversation nobody
// signed in to does not name the channel twice.
export function detailsOf(
  row: { email: string | null; turns: number; started_at: number; last_at: number },
  now?: number,
): string {
  const parts = row.email ? [row.email] : [];
  parts.push(turnsLabel(row.turns), `started ${when(row.started_at, now)}`, `last ${when(row.last_at, now)}`);
  return parts.join(', ');
}

// "expires 15:57" while a proposal still waits for its PIN. The server marks
// overdue proposals expired before every read, so pending means not yet.
export function expiresLabel(action: MessageAction): string | null {
  return action.status === 'pending' ? `expires ${clock(action.expires_at)}` : null;
}

export interface SaidTurn {
  kind: 'said';
  key: string;
  role: string;
  at: number;
  text: string;
  // The model that wrote an answer, when the server recorded one.
  model: string | null;
  action: MessageAction | null;
}

export interface CallTurn {
  kind: 'call';
  key: string;
  at: number;
  name: string;
  args: string;
  result: MessageRow | null;
  // The proposal the call made, from its result.
  action: MessageAction | null;
}

export interface ResultTurn {
  kind: 'result';
  key: string;
  at: number;
  name: string | null;
  content: string | null;
  action: MessageAction | null;
}

export type Turn = SaidTurn | CallTurn | ResultTurn;

// The transcript as the screen shows it: what was said, in order, and each
// tool call with the result it got. A tool message that answers a call in this
// conversation is shown under that call; any other tool message stands alone.
export function buildTurns(messages: MessageRow[]): Turn[] {
  const callIds = new Set<string>();
  for (const m of messages) for (const call of m.tool_calls) callIds.add(call.id);

  const results = new Map<string, MessageRow>();
  for (const m of messages) {
    if (m.role !== 'tool' || !m.tool_call_id) continue;
    if (callIds.has(m.tool_call_id) && !results.has(m.tool_call_id)) results.set(m.tool_call_id, m);
  }

  const turns: Turn[] = [];
  for (const m of messages) {
    if (m.role === 'tool') {
      if (m.tool_call_id && results.get(m.tool_call_id) === m) continue;
      turns.push({ kind: 'result', key: `m${m.id}`, at: m.at, name: m.name, content: m.content, action: m.action ?? null });
      continue;
    }
    const text = m.content ?? '';
    // An answer that only called tools has no text of its own to show, unless
    // it carries a proposal.
    if (text || m.tool_calls.length === 0 || m.action) {
      turns.push({
        kind: 'said',
        key: `m${m.id}`,
        role: m.role,
        at: m.at,
        text,
        model: m.model ?? null,
        action: m.action ?? null,
      });
    }
    for (const call of m.tool_calls) {
      const result = results.get(call.id) ?? null;
      turns.push({
        kind: 'call',
        key: `m${m.id}-${call.id}`,
        at: m.at,
        name: call.name,
        args: call.arguments,
        result,
        action: result?.action ?? null,
      });
    }
  }
  return turns;
}

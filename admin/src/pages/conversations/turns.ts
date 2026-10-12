import type { MessageRow } from '../../api/endpoints';
import { count } from '../../lib/format';

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

// Turns are the questions asked, which is how the list counts them.
export function turnsLabel(n: number): string {
  return `${count(n)} ${n === 1 ? 'turn' : 'turns'}`;
}

export function countTurns(messages: MessageRow[]): number {
  return messages.filter((m) => m.role === 'user').length;
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

// A conversation is named after the first thing the user said.
export function titleOf(messages: MessageRow[], fallback: string): string {
  const first = messages.find((m) => m.role === 'user' && m.content?.trim());
  return first?.content ? cut(first.content, 80) : fallback;
}

export interface SaidTurn {
  kind: 'said';
  key: string;
  role: string;
  at: number;
  text: string;
}

export interface CallTurn {
  kind: 'call';
  key: string;
  at: number;
  name: string;
  args: string;
  result: MessageRow | null;
}

export interface ResultTurn {
  kind: 'result';
  key: string;
  at: number;
  name: string | null;
  content: string | null;
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
      turns.push({ kind: 'result', key: `m${m.id}`, at: m.at, name: m.name, content: m.content });
      continue;
    }
    const text = m.content ?? '';
    // An answer that only called tools has no text of its own to show.
    if (text || m.tool_calls.length === 0) {
      turns.push({ kind: 'said', key: `m${m.id}`, role: m.role, at: m.at, text });
    }
    for (const call of m.tool_calls) {
      turns.push({
        kind: 'call',
        key: `m${m.id}-${call.id}`,
        at: m.at,
        name: call.name,
        args: call.arguments,
        result: results.get(call.id) ?? null,
      });
    }
  }
  return turns;
}

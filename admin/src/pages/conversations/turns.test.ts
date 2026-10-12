import { describe, expect, it } from 'vitest';
import type { MessageRow } from '../../api/endpoints';
import {
  actionsHref,
  buildTurns,
  cut,
  detailsOf,
  expiresLabel,
  hrefOf,
  idFromParam,
  titleOf,
  turnsLabel,
  whoLabel,
  whoOf,
  type MessageAction,
} from './turns';

// Node applies a change to TZ at once; the formatters are built per call.
process.env.TZ = 'UTC';

// Monday 12 October 2026, 15:55 UTC.
const T = Date.UTC(2026, 9, 12, 15, 55) / 1000;

let nextId = 100;
function msg(role: string, content: string | null, extra: Partial<MessageRow> = {}): MessageRow {
  nextId += 1;
  return { id: nextId, at: 1_791_800_000 + nextId, role, content, tool_calls: [], tool_call_id: null, name: null, ...extra };
}

const call = (id: string, name: string, args: string) => ({ id, name, arguments: args });

const proposal = (status: string): MessageAction => ({
  id: 'act_9f2464dbcbf6e8c0',
  tool: 'cancel_appointment',
  summary: 'Cancel appointment #17: Avery Example on Tuesday 20 October at 09:30',
  status,
  expires_at: T + 120,
});

describe('buildTurns', () => {
  it('shows a tool result under the call it answers', () => {
    const result = msg('tool', '{"free": ["09:00"]}', { tool_call_id: 'c1', name: 'find_slots' });
    const turns = buildTurns([
      msg('user', 'find slots tomorrow'),
      msg('assistant', '', { tool_calls: [call('c1', 'find_slots', '{"date": "2026-10-13"}')] }),
      result,
      msg('assistant', 'Free at 09:00.'),
    ]);
    expect(turns.map((t) => t.kind)).toEqual(['said', 'call', 'said']);
    const turn = turns[1];
    expect(turn?.kind === 'call' && turn.name).toBe('find_slots');
    expect(turn?.kind === 'call' && turn.args).toBe('{"date": "2026-10-13"}');
    expect(turn?.kind === 'call' && turn.result).toBe(result);
  });

  it('keeps every call of one answer, in order, each with its own result', () => {
    const turns = buildTurns([
      msg('assistant', 'Checking both.', {
        tool_calls: [call('a', 'find_slots', '{}'), call('b', 'list_appointments', '{}')],
      }),
      msg('tool', '[]', { tool_call_id: 'b', name: 'list_appointments' }),
      msg('tool', '{}', { tool_call_id: 'a', name: 'find_slots' }),
    ]);
    expect(turns.map((t) => (t.kind === 'call' ? t.name : t.kind))).toEqual(['said', 'find_slots', 'list_appointments']);
    expect(turns.every((t) => t.kind !== 'call' || t.result?.tool_call_id === (t.name === 'find_slots' ? 'a' : 'b'))).toBe(true);
  });

  it('shows a tool message on its own when nothing called it', () => {
    const turns = buildTurns([msg('tool', '{"ok": true}', { tool_call_id: 'gone', name: 'find_slots' })]);
    expect(turns).toHaveLength(1);
    expect(turns[0]?.kind).toBe('result');
    expect(turns[0]?.kind === 'result' && turns[0].name).toBe('find_slots');
  });

  it('leaves a call without a result marked as such', () => {
    const turns = buildTurns([msg('assistant', null, { tool_calls: [call('c9', 'cancel_appointment', '{"id": 17}')] })]);
    expect(turns).toHaveLength(1);
    expect(turns[0]?.kind === 'call' && turns[0].result).toBeNull();
    expect(turns[0]?.kind === 'call' && turns[0].action).toBeNull();
  });

  it('keeps an empty answer that called no tools, so a silent reply is visible', () => {
    const turns = buildTurns([msg('user', 'hello'), msg('assistant', '')]);
    expect(turns.map((t) => t.kind === 'said' && t.text)).toEqual(['hello', '']);
  });

  it('gives an empty transcript no turns', () => {
    expect(buildTurns([])).toEqual([]);
  });

  it('shows the proposal a tool result carries under the call that made it', () => {
    const action = proposal('pending');
    const turns = buildTurns([
      msg('user', 'cancel appointment 17'),
      msg('assistant', '', { tool_calls: [call('c1', 'cancel_appointment', '{"id": 17}')] }),
      msg('tool', '{"status": "pending_confirmation"}', { tool_call_id: 'c1', name: 'cancel_appointment', action }),
      msg('assistant', "I've prepared this. Confirm it with your PIN to go ahead."),
    ]);
    expect(turns.map((t) => t.kind)).toEqual(['said', 'call', 'said']);
    expect(turns[1]?.kind === 'call' && turns[1].action).toBe(action);
    expect(turns[2]?.kind === 'said' && turns[2].action).toBeNull();
  });

  it('keeps the proposal of a tool result nothing called', () => {
    const action = proposal('executed');
    const turns = buildTurns([msg('tool', '{}', { tool_call_id: 'gone', name: 'cancel_appointment', action })]);
    expect(turns[0]?.kind === 'result' && turns[0].action).toBe(action);
  });

  it('shows an answer that carries a proposal even when it only called tools', () => {
    const action = proposal('expired');
    const turns = buildTurns([
      msg('assistant', '', { tool_calls: [call('c1', 'cancel_appointment', '{"id": 17}')], action }),
    ]);
    expect(turns.map((t) => t.kind)).toEqual(['said', 'call']);
    expect(turns[0]?.kind === 'said' && turns[0].action).toBe(action);
    expect(turns[1]?.kind === 'call' && turns[1].action).toBeNull();
  });

  it('keeps the model that wrote an answer', () => {
    const turns = buildTurns([
      msg('user', 'hello'),
      msg('assistant', 'Hello.', { model: 'demo:router' }),
      msg('assistant', 'Still here.'),
    ]);
    expect(turns.map((t) => t.kind === 'said' && t.model)).toEqual([null, 'demo:router', null]);
  });
});

describe('titleOf and cut', () => {
  it('names the conversation after its preview', () => {
    expect(titleOf({ id: 'web:1:abc', preview: '  show   appointments for Avery ' })).toBe('show appointments for Avery');
  });

  it('falls back to the id without a preview', () => {
    expect(titleOf({ id: 'web:1:abc' })).toBe('web:1:abc');
    expect(titleOf({ id: 'web:1:abc', preview: null })).toBe('web:1:abc');
    expect(titleOf({ id: 'web:1:abc', preview: '   ' })).toBe('web:1:abc');
  });

  it('keeps the title to 80 characters', () => {
    const title = titleOf({ id: 'web:1:abc', preview: 'x'.repeat(120) });
    expect(title).toHaveLength(80);
    expect(title.endsWith('…')).toBe(true);
  });

  it('cuts to 80 characters, ellipsis included', () => {
    const long = 'x'.repeat(100);
    expect(cut(long, 80)).toHaveLength(80);
    expect(cut(long, 80).endsWith('…')).toBe(true);
    expect(cut('x'.repeat(80), 80)).toBe('x'.repeat(80));
    expect(cut('a word '.repeat(20), 20)).toBe('a word a word a wor…');
  });
});

describe('detailsOf', () => {
  const row = { email: 'owner@example.com', turns: 2, started_at: T, last_at: T + 120 };

  it('reads who, how long, and when', () => {
    expect(detailsOf(row, T + 3600)).toBe('owner@example.com, 2 turns, started 15:55, last 15:57');
  });

  it('leaves out who when nobody signed in', () => {
    expect(detailsOf({ ...row, email: null, turns: 1 }, T + 3600)).toBe('1 turn, started 15:55, last 15:57');
  });

  it('names the day once it is not today', () => {
    expect(detailsOf(row, T + 86400)).toBe('owner@example.com, 2 turns, started 12 Oct, 15:55, last 12 Oct, 15:57');
  });
});

describe('expiresLabel', () => {
  it('says when a pending proposal runs out', () => {
    expect(expiresLabel(proposal('pending'))).toBe('expires 15:57');
  });

  it('says nothing once it is decided or over', () => {
    for (const status of ['executing', 'executed', 'failed', 'cancelled', 'expired']) {
      expect(expiresLabel(proposal(status))).toBeNull();
    }
  });
});

describe('turns', () => {
  it('labels one and many', () => {
    expect(turnsLabel(1)).toBe('1 turn');
    expect(turnsLabel(3)).toBe('3 turns');
    expect(turnsLabel(0)).toBe('0 turns');
    expect(turnsLabel(1234)).toBe('1,234 turns');
  });
});

describe('ids in the path', () => {
  it('encodes the colons on the way out and decodes them on the way in', () => {
    expect(hrefOf('web:1:bd69fe7be6c2')).toBe('/conversations/web%3A1%3Abd69fe7be6c2');
    expect(idFromParam('web%3A1%3Abd69fe7be6c2')).toBe('web:1:bd69fe7be6c2');
    expect(idFromParam('web:1:bd69fe7be6c2')).toBe('web:1:bd69fe7be6c2');
  });
  it('keeps a param it cannot decode', () => {
    expect(idFromParam('100%')).toBe('100%');
  });
  it('links to the Actions screen by status', () => {
    expect(actionsHref('pending')).toBe('/actions?status=pending');
    expect(actionsHref('')).toBe('/actions');
  });
});

describe('who', () => {
  it('names the account, or the channel without one', () => {
    expect(whoOf({ email: 'owner@example.com', channel: 'web' })).toBe('owner@example.com');
    expect(whoOf({ email: null, channel: 'telegram' })).toBe('telegram');
  });
  it('labels the speakers', () => {
    expect(whoLabel('user')).toBe('User');
    expect(whoLabel('assistant')).toBe('Ira');
    expect(whoLabel('system')).toBe('System');
    expect(whoLabel('')).toBe('Unknown');
  });
});

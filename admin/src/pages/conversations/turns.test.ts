import { describe, expect, it } from 'vitest';
import type { MessageRow } from '../../api/endpoints';
import {
  buildTurns,
  countTurns,
  cut,
  hrefOf,
  idFromParam,
  titleOf,
  turnsLabel,
  whoLabel,
  whoOf,
} from './turns';

let nextId = 100;
function msg(role: string, content: string | null, extra: Partial<MessageRow> = {}): MessageRow {
  nextId += 1;
  return { id: nextId, at: 1_791_800_000 + nextId, role, content, tool_calls: [], tool_call_id: null, name: null, ...extra };
}

const call = (id: string, name: string, args: string) => ({ id, name, arguments: args });

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
  });

  it('keeps an empty answer that called no tools, so a silent reply is visible', () => {
    const turns = buildTurns([msg('user', 'hello'), msg('assistant', '')]);
    expect(turns.map((t) => t.kind === 'said' && t.text)).toEqual(['hello', '']);
  });

  it('gives an empty transcript no turns', () => {
    expect(buildTurns([])).toEqual([]);
  });
});

describe('titleOf and cut', () => {
  it('names the conversation after the first user message', () => {
    const messages = [msg('assistant', 'Hello'), msg('user', '  show   appointments\nfor Avery '), msg('user', 'later')];
    expect(titleOf(messages, 'web:1:abc')).toBe('show appointments for Avery');
  });

  it('falls back to the id when nobody said anything', () => {
    expect(titleOf([], 'web:1:abc')).toBe('web:1:abc');
    expect(titleOf([msg('user', '   '), msg('assistant', 'Hi')], 'web:1:abc')).toBe('web:1:abc');
  });

  it('cuts to 80 characters, ellipsis included', () => {
    const long = 'x'.repeat(100);
    expect(cut(long, 80)).toHaveLength(80);
    expect(cut(long, 80).endsWith('…')).toBe(true);
    expect(cut('x'.repeat(80), 80)).toBe('x'.repeat(80));
    expect(cut('a word '.repeat(20), 20)).toBe('a word a word a wor…');
  });
});

describe('turns', () => {
  it('counts the questions asked', () => {
    expect(countTurns([msg('user', 'a'), msg('assistant', 'b'), msg('tool', 'c'), msg('user', 'd')])).toBe(2);
  });
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

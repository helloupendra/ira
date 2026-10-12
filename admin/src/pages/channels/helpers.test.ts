import { describe, expect, it } from 'vitest';
import type { ChannelView } from '../../api/endpoints';
import {
  address,
  extraLines,
  flag,
  pairedChats,
  sortChannels,
  speechToText,
  spokenReplies,
  text,
  tokenEnv,
  tokenState,
  voiceReplies,
} from './helpers';

const channel = (name: string): ChannelView => ({ name, enabled: true, detail: {} });

describe('sortChannels', () => {
  it('puts web, http and telegram first and keeps the rest in the order sent', () => {
    const sorted = sortChannels([channel('sms'), channel('telegram'), channel('http'), channel('web'), channel('slack')]);
    expect(sorted.map((c) => c.name)).toEqual(['web', 'http', 'telegram', 'sms', 'slack']);
  });

  it('does not change the list it was given', () => {
    const list = [channel('telegram'), channel('web')];
    sortChannels(list);
    expect(list.map((c) => c.name)).toEqual(['telegram', 'web']);
  });
});

describe('text', () => {
  it('leaves out nothing-values and spells out the rest', () => {
    expect(text(null)).toBeNull();
    expect(text(undefined)).toBeNull();
    expect(text('')).toBeNull();
    expect(text('whisper')).toBe('whisper');
    expect(text(8765)).toBe('8765');
    expect(text(false)).toBe('false');
    expect(text({ a: 1 })).toBe('{"a":1}');
  });
});

describe('web', () => {
  it('names the speech services, with plain words when one is off', () => {
    expect(speechToText({ stt: 'whisper' })).toBe('whisper');
    expect(speechToText({ stt: null })).toBe('not set up');
    expect(speechToText({})).toBe('not set up');
    expect(spokenReplies({ tts: 'polly' })).toBe('polly');
    expect(spokenReplies({ tts: null })).toBe("the browser's own voice");
  });
});

describe('address', () => {
  it('joins host and port and copes with a missing half', () => {
    expect(address({ host: '127.0.0.1', port: 8765 })).toBe('127.0.0.1:8765');
    expect(address({ host: '0.0.0.0' })).toBe('0.0.0.0');
    expect(address({ port: 8765 })).toBe('8765');
    expect(address({})).toBeNull();
  });
});

describe('telegram', () => {
  it('counts paired chats only when the server sent a number', () => {
    expect(pairedChats({ paired_chats: 0 })).toBe('0');
    expect(pairedChats({ paired_chats: 1200 })).toBe('1,200');
    expect(pairedChats({})).toBeNull();
  });

  it('reports the token and its variable', () => {
    expect(tokenState({ token_present: false, token_env: 'TELEGRAM_BOT_TOKEN' })).toEqual({
      present: false,
      env: 'TELEGRAM_BOT_TOKEN',
    });
    expect(tokenState({ token_present: true })).toEqual({ present: true, env: null });
    expect(tokenState({ token_env: 'X' })).toBeNull();
  });

  it('names the variable the pairing steps use', () => {
    expect(tokenEnv({ token_env: 'CLINIC_BOT' })).toBe('CLINIC_BOT');
    expect(tokenEnv({})).toBe('TELEGRAM_BOT_TOKEN');
  });

  it('turns voice_replies into a sentence and passes an unknown value through', () => {
    expect(voiceReplies({ voice_replies: 'off' })).toBe('off: replies are text only');
    expect(voiceReplies({ voice_replies: 'voice' })).toBe('voice: a voice note is answered with a voice note');
    expect(voiceReplies({ voice_replies: 'always' })).toBe('always: every reply is a voice note');
    expect(voiceReplies({ voice_replies: 'sometimes' })).toBe('sometimes');
    expect(voiceReplies({})).toBeNull();
  });

  it('reads a flag only when it is a boolean', () => {
    expect(flag(true)).toBe(true);
    expect(flag(false)).toBe(false);
    expect(flag('yes')).toBeNull();
    expect(flag(undefined)).toBeNull();
  });
});

describe('extraLines', () => {
  it('shows the fields the page has no sentence for, as words', () => {
    const detail = { paired_chats: 2, last_error: 'timed out', retry_after: 30, note: null, nested: { a: 1 } };
    expect(extraLines(detail, ['paired_chats'])).toEqual([
      ['last error', 'timed out'],
      ['retry after', '30'],
      ['nested', '{"a":1}'],
    ]);
  });

  it('is empty when every field is known', () => {
    expect(extraLines({ stt: 'fake', tts: null }, ['stt', 'tts'])).toEqual([]);
  });
});

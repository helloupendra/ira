import { describe, expect, it } from 'vitest';
import { ApiError } from '../../api/client';
import type { ChannelView, ServerAddress } from '../../api/endpoints';
import {
  botHandle,
  botUnknown,
  chatName,
  codeLife,
  describeAddress,
  extraLines,
  failureText,
  httpUrl,
  pairChoices,
  pairedCount,
  pairingNote,
  runningBadge,
  setupReason,
  sortChannels,
  speechToText,
  spokenReplies,
  text,
  userLabel,
  voiceReplies,
} from './helpers';

// Node applies a change to TZ at once; the formatters are built per call.
process.env.TZ = 'UTC';

const channel = (name: string): ChannelView => ({ name, enabled: true, detail: {} });

const local: ServerAddress = {
  host: '127.0.0.1',
  port: 8790,
  configured_host: '127.0.0.1',
  configured_port: 8790,
  public_url: null,
  url: 'http://127.0.0.1:8790',
};

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

describe('describeAddress', () => {
  it('shows the url as the address when nothing differs', () => {
    expect(describeAddress(local)).toEqual({
      label: 'Address',
      url: 'http://127.0.0.1:8790',
      bound: '127.0.0.1:8790',
      configured: null,
    });
  });

  it('calls a public_url the public address', () => {
    const info = describeAddress({ ...local, public_url: 'https://ira.example.com', url: 'https://ira.example.com' });
    expect(info.label).toBe('Public address');
    expect(info.url).toBe('https://ira.example.com');
  });

  it('says what ira.yaml asked for only when serve bound something else', () => {
    expect(describeAddress({ ...local, configured_port: 8765 }).configured).toBe('127.0.0.1:8765');
    expect(describeAddress({ ...local, host: '0.0.0.0', configured_host: '0.0.0.0' }).configured).toBeNull();
  });
});

describe('httpUrl', () => {
  it('is the http channel address, or null without one', () => {
    const http: ChannelView = { name: 'http', enabled: true, detail: {}, address: local };
    expect(httpUrl([channel('web'), http])).toBe('http://127.0.0.1:8790');
    expect(httpUrl([channel('web'), { ...http, address: null }])).toBeNull();
    expect(httpUrl([channel('web')])).toBeNull();
  });
});

describe('telegram', () => {
  const view = { enabled: true, token_present: true, token_env: 'TELEGRAM_BOT_TOKEN', running: true };

  it('names a chat, falling back to its id', () => {
    expect(chatName({ chat_id: 5550100, name: 'Riley Demo (@riley)' })).toBe('Riley Demo (@riley)');
    expect(chatName({ chat_id: 5550100, name: null })).toBe('Chat 5550100');
    expect(chatName({ chat_id: 7, name: '  ' })).toBe('Chat 7');
  });

  it('writes the bot as a handle without doubling the at sign', () => {
    expect(botHandle('sunrise_dental_bot')).toBe('@sunrise_dental_bot');
    expect(botHandle('@sunrise_dental_bot')).toBe('@sunrise_dental_bot');
  });

  it('says why the bot has no name yet', () => {
    expect(botUnknown({ token_present: false })).toBe('unknown until the token is set');
    expect(botUnknown({ token_present: true })).toBe('not known yet; Telegram has not answered');
  });

  it('colours the running badge by whether the bot should be polling', () => {
    expect(runningBadge(view)).toBe('badge badge-ok');
    expect(runningBadge({ ...view, running: false })).toBe('badge badge-warn');
    expect(runningBadge({ ...view, running: false, enabled: false })).toBe('badge badge-muted');
    expect(runningBadge({ ...view, running: false, token_present: false })).toBe('badge badge-muted');
  });

  it('knows what setup is still missing', () => {
    expect(setupReason(view)).toBeNull();
    expect(setupReason({ ...view, enabled: false })).toBe('Telegram is off in ira.yaml');
    expect(setupReason({ ...view, token_present: false })).toBe('the bot token (TELEGRAM_BOT_TOKEN) is not set');
    expect(setupReason({ ...view, enabled: false, token_present: false })).toBe('Telegram is off in ira.yaml');
  });

  it('counts paired chats in words', () => {
    expect(pairedCount(0)).toBe('0 paired chats');
    expect(pairedCount(1)).toBe('1 paired chat');
    expect(pairedCount(1200)).toBe('1,200 paired chats');
  });

  it('turns voice_replies into a sentence and passes an unknown value through', () => {
    expect(voiceReplies({ voice_replies: 'off' })).toBe('off: replies are text only');
    expect(voiceReplies({ voice_replies: 'voice' })).toBe('voice: a voice note is answered with a voice note');
    expect(voiceReplies({ voice_replies: 'always' })).toBe('always: every reply is a voice note');
    expect(voiceReplies({ voice_replies: 'sometimes' })).toBe('sometimes');
    expect(voiceReplies({})).toBeNull();
  });
});

describe('pairing', () => {
  // Monday 12 October 2026, 14:32 UTC.
  const expires = Date.UTC(2026, 9, 12, 14, 32) / 1000;

  it('says how long a code lasts in minutes, or seconds for a short one', () => {
    expect(codeLife(600)).toBe('10 minutes');
    expect(codeLife(60)).toBe('1 minute');
    expect(codeLife(90)).toBe('1 minute');
    expect(codeLife(45)).toBe('45 seconds');
    expect(codeLife(1)).toBe('1 second');
  });

  it('tells the person what to send, by when, and as whom', () => {
    expect(pairingNote({ expires_at: expires, email: 'owner@example.com' }, 600)).toBe(
      'Send this to the bot within 10 minutes (expires 14:32); the chat then acts as owner@example.com.',
    );
  });

  it('lists you first and labels each account with its role', () => {
    const users = [
      { id: 1, email: 'owner@example.com', role: 'owner', created_at: 0, has_pin: true },
      { id: 2, email: 'admin@example.com', role: 'admin', created_at: 0, has_pin: true },
      { id: 3, email: 'staff@example.com', role: 'staff', created_at: 0, has_pin: false },
    ];
    expect(pairChoices(users, 2).map((u) => u.id)).toEqual([2, 1, 3]);
    expect(pairChoices(users, undefined).map((u) => u.id)).toEqual([1, 2, 3]);
    expect(userLabel(users[1]!, 2)).toBe('admin@example.com (Admin, you)');
    expect(userLabel(users[2]!, 2)).toBe('staff@example.com (Staff)');
  });
});

describe('failureText', () => {
  it('uses the server detail as a sentence', () => {
    expect(failureText(new ApiError(404, 'No such paired chat'))).toBe('No such paired chat.');
    expect(failureText(new ApiError(403, 'Not allowed for your role.'))).toBe('Not allowed for your role.');
    expect(failureText(new ApiError(0, 'Cannot reach the server'))).toBe(
      'Cannot reach the server. Check the connection and try again.',
    );
    expect(failureText(new Error('boom'))).toBe('Something went wrong. Try again.');
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

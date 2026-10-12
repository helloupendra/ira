import { describe, expect, it } from 'vitest';
import type { ChannelView } from '../../api/endpoints';
import { channelLine, sortChannels, telegramTokenEnv } from './channels';

const web: ChannelView = { name: 'web', enabled: true, detail: { stt: 'fake', tts: null } };
const http: ChannelView = { name: 'http', enabled: true, detail: { host: '127.0.0.1', port: 8765 } };
const telegram: ChannelView = {
  name: 'telegram',
  enabled: false,
  detail: { paired_chats: 0, token_env: 'TELEGRAM_BOT_TOKEN', token_present: false, voice_replies: 'voice' },
};

describe('sortChannels', () => {
  it('puts web, then the API, then Telegram, then anything else by name', () => {
    const other: ChannelView = { name: 'sms', enabled: false };
    expect(sortChannels([telegram, other, http, web]).map((c) => c.name)).toEqual(['web', 'http', 'telegram', 'sms']);
  });
});

describe('channelLine', () => {
  it('says how the web app hears and speaks', () => {
    expect(channelLine(web)).toBe('Speech to text: fake. Voice: the browser.');
    expect(channelLine({ ...web, detail: { stt: null, tts: 'polly' } })).toBe('Speech to text: none. Voice: polly.');
  });

  it('says where the API listens', () => {
    expect(channelLine(http)).toBe('Listening on 127.0.0.1:8765.');
    expect(channelLine({ name: 'http', enabled: true })).toBeNull();
  });

  it('counts paired chats and names the token variable', () => {
    expect(channelLine(telegram)).toBe('0 paired chats. TELEGRAM_BOT_TOKEN missing.');
    expect(channelLine({ ...telegram, detail: { paired_chats: 1, token_env: 'TG', token_present: true } })).toBe(
      '1 paired chat. TG set.',
    );
    expect(channelLine({ name: 'telegram', enabled: false })).toBeNull();
  });

  it('has nothing to say about a channel it does not know', () => {
    expect(channelLine({ name: 'sms', enabled: true, detail: { number: '+1 555 0100' } })).toBeNull();
  });
});

describe('telegramTokenEnv', () => {
  it('uses the name the server reports, with the usual one as a fallback', () => {
    expect(telegramTokenEnv([web, { ...telegram, detail: { token_env: 'MY_BOT' } }])).toBe('MY_BOT');
    expect(telegramTokenEnv([web, http])).toBe('TELEGRAM_BOT_TOKEN');
    expect(telegramTokenEnv([])).toBe('TELEGRAM_BOT_TOKEN');
  });
});

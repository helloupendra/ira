import { describe, expect, it } from 'vitest';
import type { ChannelView, ServerAddress, TelegramView } from '../../api/endpoints';
import {
  addressLine,
  channelLine,
  codeLife,
  httpAddress,
  localOnly,
  pairingNote,
  setupReason,
  sortChannels,
  telegramLine,
} from './channels';

// Node applies a change to TZ at once; the formatters are built per call.
process.env.TZ = 'UTC';

// Monday 12 October 2026, 14:32 UTC.
const NOW = Date.UTC(2026, 9, 12, 14, 32) / 1000;

const local: ServerAddress = {
  host: '127.0.0.1',
  port: 8790,
  configured_host: '127.0.0.1',
  configured_port: 8765,
  public_url: null,
  url: 'http://127.0.0.1:8790',
};
const published: ServerAddress = {
  host: '0.0.0.0',
  port: 8790,
  configured_host: '0.0.0.0',
  configured_port: 8790,
  public_url: 'https://ira.example.com',
  url: 'https://ira.example.com',
};

const web: ChannelView = { name: 'web', enabled: true, detail: { stt: 'fake', tts: null }, address: null };
const http: ChannelView = { name: 'http', enabled: true, detail: { host: '127.0.0.1', port: 8790 }, address: local };
const telegram: ChannelView = { name: 'telegram', enabled: false, detail: { paired_chats: 0 }, address: null };

const view = (over: Partial<TelegramView> = {}): TelegramView => ({
  enabled: false,
  token_env: 'TELEGRAM_BOT_TOKEN',
  token_present: false,
  bot_username: null,
  bot_link: null,
  bot_error: null,
  running: false,
  last_poll_at: null,
  last_error: null,
  pairing_seconds: 600,
  chats: [],
  ...over,
});
const chat = { chat_id: 1001, name: 'Riley Demo (@riley)', paired_at: NOW - 86400, user_id: 1, email: 'owner@example.com', role: 'owner' };

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

  it('says what to open for the API, and where it listens when that differs', () => {
    expect(channelLine(http)).toBe('Open http://127.0.0.1:8790.');
    expect(channelLine({ ...http, address: published })).toBe('Open https://ira.example.com. Listens on 0.0.0.0:8790.');
    expect(addressLine({ ...local, host: '0.0.0.0' })).toBe('Open http://127.0.0.1:8790. Listens on 0.0.0.0:8790.');
    expect(channelLine({ name: 'http', enabled: true })).toBeNull();
  });

  it('leaves Telegram to its own view, and has nothing for a channel it does not know', () => {
    expect(channelLine(telegram)).toBeNull();
    expect(channelLine({ name: 'sms', enabled: true, detail: { number: '+1 555 0100' } })).toBeNull();
  });
});

describe('the address a phone opens', () => {
  it("is the http channel's, when the server reported one", () => {
    expect(httpAddress([web, http, telegram])).toBe(local);
    expect(httpAddress([web, { name: 'http', enabled: true }])).toBeNull();
    expect(httpAddress([])).toBeNull();
  });

  it('knows when only this computer can open it', () => {
    expect(localOnly(local)).toBe(true);
    expect(localOnly({ ...local, url: 'http://localhost:8790' })).toBe(true);
    expect(localOnly({ ...local, host: '192.168.1.20', url: 'http://192.168.1.20:8790' })).toBe(false);
    expect(localOnly(published)).toBe(false);
    expect(localOnly({ ...local, url: 'not an address' })).toBe(false);
  });
});

describe('telegramLine', () => {
  it('says there is no bot until the token is set', () => {
    expect(telegramLine(view())).toBe('No bot until the token is set. 0 paired chats. TELEGRAM_BOT_TOKEN missing.');
  });

  it('names the bot, says whether it runs, and counts the chats', () => {
    expect(
      telegramLine(view({ enabled: true, token_present: true, bot_username: 'sunrise_bot', running: true, chats: [chat] })),
    ).toBe('Bot @sunrise_bot, running. 1 paired chat. TELEGRAM_BOT_TOKEN set.');
    expect(telegramLine(view({ enabled: true, token_present: true, bot_username: '@sunrise_bot' }))).toBe(
      'Bot @sunrise_bot, not running. 0 paired chats. TELEGRAM_BOT_TOKEN set.',
    );
    expect(telegramLine(view({ token_present: true, bot_username: 'sunrise_bot' }))).toBe(
      'Bot @sunrise_bot. 0 paired chats. TELEGRAM_BOT_TOKEN set.',
    );
  });

  it('says why there is no name yet once the token is set', () => {
    expect(telegramLine(view({ token_present: true }))).toBe('Bot not known yet. 0 paired chats. TELEGRAM_BOT_TOKEN set.');
    expect(telegramLine(view({ token_present: true, bot_error: 'Telegram answered 401.' }))).toBe(
      'Bot not known (Telegram answered 401). 0 paired chats. TELEGRAM_BOT_TOKEN set.',
    );
  });
});

describe('pairing', () => {
  it('says what stops the bot from answering', () => {
    expect(setupReason(view())).toBe('Telegram is off in ira.yaml');
    expect(setupReason(view({ enabled: true }))).toBe('the bot token (TELEGRAM_BOT_TOKEN) is not set');
    expect(setupReason(view({ enabled: true, token_present: true }))).toBeNull();
  });

  it('says how long a code works in plain units', () => {
    expect(codeLife(600)).toBe('10 minutes');
    expect(codeLife(60)).toBe('1 minute');
    expect(codeLife(90)).toBe('1 minute');
    expect(codeLife(45)).toBe('45 seconds');
  });

  it('says until when the code works and who the chat becomes', () => {
    expect(pairingNote({ expires_at: NOW + 600, email: 'owner@example.com' })).toBe(
      'Works until 14:42; the chat then acts as owner@example.com.',
    );
  });
});

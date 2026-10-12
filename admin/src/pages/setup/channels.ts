import type { ChannelView } from '../../api/endpoints';
import { count } from '../../lib/format';

const ORDER = ['web', 'http', 'telegram'];

export const CHANNEL_LABELS: Record<string, string> = { web: 'Web app', http: 'HTTP API', telegram: 'Telegram' };

// What each channel is for, in one line.
export const CHANNEL_BLURBS: Record<string, string> = {
  web: 'The Ira app at /: talk or type in a browser, with spoken replies.',
  http: 'For programs, with a token from Tokens & security.',
  telegram: 'A bot in Telegram; each paired chat acts as the person who paired it.',
};

export const DEFAULT_TOKEN_ENV = 'TELEGRAM_BOT_TOKEN';

function text(value: unknown): string | null {
  if (value === null || value === undefined || value === '') return null;
  return typeof value === 'string' ? value : typeof value === 'number' || typeof value === 'boolean' ? String(value) : null;
}

export function sortChannels(channels: readonly ChannelView[]): ChannelView[] {
  const rank = (name: string) => {
    const i = ORDER.indexOf(name);
    return i === -1 ? ORDER.length : i;
  };
  return [...channels].sort((a, b) => rank(a.name) - rank(b.name) || a.name.localeCompare(b.name));
}

// A short line under the channel from the fields the server reports, or
// nothing when it reports none worth a line.
export function channelLine(channel: ChannelView): string | null {
  const d = channel.detail ?? {};
  if (channel.name === 'web') {
    return `Speech to text: ${text(d.stt) ?? 'none'}. Voice: ${text(d.tts) ?? 'the browser'}.`;
  }
  if (channel.name === 'http') {
    const where = [text(d.host), text(d.port)].filter(Boolean).join(':');
    return where ? `Listening on ${where}.` : null;
  }
  if (channel.name === 'telegram') {
    const parts: string[] = [];
    const paired = d.paired_chats;
    if (typeof paired === 'number') parts.push(`${count(paired)} paired ${paired === 1 ? 'chat' : 'chats'}`);
    const env = text(d.token_env);
    if (env) {
      const state = d.token_present === true ? 'set' : d.token_present === false ? 'missing' : null;
      parts.push(state ? `${env} ${state}` : env);
    }
    return parts.length > 0 ? `${parts.join('. ')}.` : null;
  }
  return null;
}

// The variable the Telegram token lives in, as the server names it.
export function telegramTokenEnv(channels: readonly ChannelView[]): string {
  const telegram = channels.find((c) => c.name === 'telegram');
  return text(telegram?.detail?.token_env) ?? DEFAULT_TOKEN_ENV;
}

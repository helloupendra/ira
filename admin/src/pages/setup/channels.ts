import type { ChannelView, ServerAddress, TelegramPairing, TelegramView } from '../../api/endpoints';
import { clock, count } from '../../lib/format';

const ORDER = ['web', 'http', 'telegram'];

export const CHANNEL_LABELS: Record<string, string> = { web: 'Web app', http: 'HTTP API', telegram: 'Telegram' };

// What each channel is for, in one line.
export const CHANNEL_BLURBS: Record<string, string> = {
  web: 'The Ira app at /: talk or type in a browser, with spoken replies.',
  http: 'For programs, with a token from Tokens & security.',
  telegram: 'A bot in Telegram; each paired chat acts as the person who paired it.',
};

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

// The http channel's address, when the server reported one.
export function httpAddress(channels: readonly ChannelView[]): ServerAddress | null {
  return channels.find((c) => c.name === 'http')?.address ?? null;
}

// What people open and, when that is another address (a public URL, or a
// wildcard host), where the server itself listens.
export function addressLine(address: ServerAddress): string {
  const bound = `${address.host}:${address.port}`;
  const open = `Open ${address.url}.`;
  return address.url === `http://${bound}` ? open : `${open} Listens on ${bound}.`;
}

const LOCAL_HOSTS = ['127.0.0.1', 'localhost', '::1', '[::1]', '0.0.0.0'];

// True when the address only works on the server's own machine and there is
// no public_url for a phone to open instead.
export function localOnly(address: ServerAddress): boolean {
  if (address.public_url) return false;
  try {
    return LOCAL_HOSTS.includes(new URL(address.url).hostname);
  } catch {
    return false;
  }
}

// A short line under the web or http channel from what the server reports,
// or nothing. Telegram's line comes from its own view: telegramLine.
export function channelLine(channel: ChannelView): string | null {
  if (channel.name === 'web') {
    const d = channel.detail ?? {};
    return `Speech to text: ${text(d.stt) ?? 'none'}. Voice: ${text(d.tts) ?? 'the browser'}.`;
  }
  if (channel.name === 'http') return channel.address ? addressLine(channel.address) : null;
  return null;
}

export function botHandle(username: string): string {
  return username.startsWith('@') ? username : `@${username}`;
}

export function pairedCount(n: number): string {
  return `${count(n)} paired ${n === 1 ? 'chat' : 'chats'}`;
}

// The bot by name once Telegram has answered, else why there is no name yet.
function botState(view: TelegramView): string {
  if (view.bot_username) {
    const bot = `Bot ${botHandle(view.bot_username)}`;
    if (!view.enabled || !view.token_present) return bot;
    return `${bot}, ${view.running ? 'running' : 'not running'}`;
  }
  if (!view.token_present) return 'No bot until the token is set';
  const why = view.bot_error?.trim();
  return why ? `Bot not known (${why.replace(/[.!?]+$/, '')})` : 'Bot not known yet';
}

// The bot, its chats and its token in one line under the Telegram row.
export function telegramLine(view: TelegramView): string {
  const token = `${view.token_env} ${view.token_present ? 'set' : 'missing'}`;
  return `${botState(view)}. ${pairedCount(view.chats.length)}. ${token}.`;
}

// What stops the bot from answering; null once the channel is on and has
// its token.
export function setupReason(view: Pick<TelegramView, 'enabled' | 'token_present' | 'token_env'>): string | null {
  if (!view.enabled) return 'Telegram is off in ira.yaml';
  if (!view.token_present) return `the bot token (${view.token_env}) is not set`;
  return null;
}

// How long a code works, in the unit people would say.
export function codeLife(seconds: number): string {
  if (seconds < 60) return `${seconds} ${seconds === 1 ? 'second' : 'seconds'}`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} ${minutes === 1 ? 'minute' : 'minutes'}`;
}

// The line under a fresh code: until when it works, and who the chat becomes.
export function pairingNote(pairing: Pick<TelegramPairing, 'expires_at' | 'email'>): string {
  return `Works until ${clock(pairing.expires_at)}; the chat then acts as ${pairing.email}.`;
}

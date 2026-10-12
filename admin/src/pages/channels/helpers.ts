import { ApiError } from '../../api/client';
import type {
  AdminUserRow,
  ChannelView,
  ServerAddress,
  TelegramChat,
  TelegramPairing,
  TelegramView,
} from '../../api/endpoints';
import { clock, count, humanize } from '../../lib/format';
import { roleLabel } from '../../lib/roles';

export type Detail = Record<string, unknown>;

// The order the page explains them in; a channel the console does not know
// yet goes last, in the order the server sent it.
const ORDER = ['web', 'http', 'telegram'];

export function sortChannels(list: readonly ChannelView[]): ChannelView[] {
  const rank = (name: string) => {
    const i = ORDER.indexOf(name);
    return i === -1 ? ORDER.length : i;
  };
  return [...list].sort((a, b) => rank(a.name) - rank(b.name));
}

// A detail value as text, or null when there is nothing worth a line.
export function text(value: unknown): string | null {
  if (value === null || value === undefined || value === '') return null;
  return typeof value === 'string' ? value : JSON.stringify(value);
}

export function speechToText(detail: Detail): string {
  return text(detail.stt) ?? 'not set up';
}

export function spokenReplies(detail: Detail): string {
  return text(detail.tts) ?? "the browser's own voice";
}

// The http address as three facts: the URL people open (labelled as public
// when it comes from public_url), what `ira serve` bound, and what ira.yaml
// asked for when that is not the same.
export interface AddressInfo {
  label: 'Address' | 'Public address';
  url: string;
  bound: string;
  configured: string | null;
}

export function describeAddress(a: ServerAddress): AddressInfo {
  const bound = `${a.host}:${a.port}`;
  const configured = `${a.configured_host}:${a.configured_port}`;
  return {
    label: a.public_url ? 'Public address' : 'Address',
    url: a.url,
    bound,
    configured: configured === bound ? null : configured,
  };
}

// The URL a phone opens: the http channel's, when the server reported one.
export function httpUrl(list: readonly ChannelView[]): string | null {
  const http = list.find((channel) => channel.name === 'http');
  return http?.address?.url ?? null;
}

// The voice_replies setting (off, voice or always in ira.yaml) as a sentence.
export function voiceReplies(detail: Detail): string | null {
  const value = text(detail.voice_replies);
  switch (value) {
    case null:
      return null;
    case 'off':
      return 'off: replies are text only';
    case 'voice':
      return 'voice: a voice note is answered with a voice note';
    case 'always':
      return 'always: every reply is a voice note';
    default:
      return value;
  }
}

// Whatever else the server sent, as label and value, so a new field shows up
// before the console has a sentence for it.
export function extraLines(detail: Detail, used: readonly string[]): [string, string][] {
  const rows: [string, string][] = [];
  for (const [key, value] of Object.entries(detail)) {
    if (used.includes(key)) continue;
    const shown = text(value);
    if (shown !== null) rows.push([humanize(key), shown]);
  }
  return rows;
}

// Telegram ---------------------------------------------------------------

export function chatName(chat: Pick<TelegramChat, 'chat_id' | 'name'>): string {
  return chat.name?.trim() || `Chat ${chat.chat_id}`;
}

export function botHandle(username: string): string {
  return username.startsWith('@') ? username : `@${username}`;
}

// Why there is no bot name to show.
export function botUnknown(view: Pick<TelegramView, 'token_present'>): string {
  return view.token_present ? 'not known yet; Telegram has not answered' : 'unknown until the token is set';
}

// Green while the bot polls; amber when it should but does not; grey while
// the channel is not set up at all.
export function runningBadge(view: Pick<TelegramView, 'running' | 'enabled' | 'token_present'>): string {
  if (view.running) return 'badge badge-ok';
  if (view.enabled && view.token_present) return 'badge badge-warn';
  return 'badge badge-muted';
}

// What stops the bot from answering, for the setup steps and the pairing
// dialog; null once the channel is on and has its token.
export function setupReason(view: Pick<TelegramView, 'enabled' | 'token_present' | 'token_env'>): string | null {
  if (!view.enabled) return 'Telegram is off in ira.yaml';
  if (!view.token_present) return `the bot token (${view.token_env}) is not set`;
  return null;
}

export function pairedCount(n: number): string {
  return `${count(n)} paired ${n === 1 ? 'chat' : 'chats'}`;
}

// How long a code works, in the unit people would say.
export function codeLife(seconds: number): string {
  if (seconds < 60) return `${seconds} second${seconds === 1 ? '' : 's'}`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} minute${minutes === 1 ? '' : 's'}`;
}

export function pairingNote(pairing: Pick<TelegramPairing, 'expires_at' | 'email'>, seconds: number): string {
  return `Send this to the bot within ${codeLife(seconds)} (expires ${clock(pairing.expires_at)}); the chat then acts as ${pairing.email}.`;
}

// The owner's choice of account: you first, then the rest as the server
// lists them.
export function pairChoices(users: readonly AdminUserRow[], meId: number | undefined): AdminUserRow[] {
  const me = users.filter((user) => user.id === meId);
  const others = users.filter((user) => user.id !== meId);
  return [...me, ...others];
}

export function userLabel(user: Pick<AdminUserRow, 'id' | 'email' | 'role'>, meId: number | undefined): string {
  const you = user.id === meId ? ', you' : '';
  return `${user.email} (${roleLabel(user.role)}${you})`;
}

// What a failed write says: the server's own detail when there is one.
export function failureText(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 0) return 'Cannot reach the server. Check the connection and try again.';
    return /[.!?]$/.test(err.detail) ? err.detail : `${err.detail}.`;
  }
  return 'Something went wrong. Try again.';
}

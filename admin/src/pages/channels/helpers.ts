import type { ChannelView } from '../../api/endpoints';
import { count, humanize } from '../../lib/format';

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

// "host:port" as ira.yaml has it; a half the server left out is skipped.
export function address(detail: Detail): string | null {
  const parts = [text(detail.host), text(detail.port)].filter((part): part is string => part !== null);
  return parts.length ? parts.join(':') : null;
}

export function pairedChats(detail: Detail): string | null {
  const n = detail.paired_chats;
  return typeof n === 'number' ? count(n) : null;
}

// Whether the bot token is in the environment, and under which name.
export function tokenState(detail: Detail): { present: boolean; env: string | null } | null {
  if (typeof detail.token_present !== 'boolean') return null;
  return { present: detail.token_present, env: text(detail.token_env) };
}

// The variable the pairing steps name: what the server reports, else the
// name the documentation uses.
export function tokenEnv(detail: Detail): string {
  return text(detail.token_env) ?? 'TELEGRAM_BOT_TOKEN';
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

export function flag(value: unknown): boolean | null {
  return typeof value === 'boolean' ? value : null;
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

import { ApiError } from '../../api/client';
import type {
  KeyView,
  ModelsView,
  ModelTestResult,
  PinStatus,
  ProviderView,
  SettingsUpdate,
  SettingsView,
  TierView,
} from '../../api/endpoints';
import { seconds } from '../../lib/format';

// The wizard's steps in order. Step 1 only shows while the owner is missing;
// the rest are remembered in localStorage so the owner can close the page
// and come back to where they were.
export const STEPS: readonly { n: number; label: string }[] = [
  { n: 1, label: 'Owner' },
  { n: 2, label: 'Name and voice' },
  { n: 3, label: 'Models' },
  { n: 4, label: 'Action PIN' },
  { n: 5, label: 'Channels' },
  { n: 6, label: 'Done' },
];
export const FIRST_STEP_AFTER_OWNER = 2;
export const LAST_STEP = 6;
export const STEP_KEY = 'ira.setup.step';

type Store = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

function browserStore(): Store | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
}

// "3" reads as step 3; anything else, or a step outside 2 to 6, is ignored.
export function parseStep(raw: string | null | undefined): number | null {
  if (raw === null || raw === undefined || !/^\d+$/.test(raw.trim())) return null;
  const n = Number(raw.trim());
  return n >= FIRST_STEP_AFTER_OWNER && n <= LAST_STEP ? n : null;
}

export function readStep(store: Store | null = browserStore()): number {
  try {
    return parseStep(store?.getItem(STEP_KEY)) ?? FIRST_STEP_AFTER_OWNER;
  } catch {
    return FIRST_STEP_AFTER_OWNER;
  }
}

// Remembers where the owner is. The last step clears it, so the next visit
// starts the tour again instead of landing on "Done".
export function writeStep(n: number, store: Store | null = browserStore()): void {
  try {
    if (n >= LAST_STEP) store?.removeItem(STEP_KEY);
    else store?.setItem(STEP_KEY, String(n));
  } catch {
    // Storage can be blocked (private mode); the step then lasts for this page only.
  }
}

export function clampStep(n: number): number {
  return Math.min(LAST_STEP, Math.max(FIRST_STEP_AFTER_OWNER, Math.round(n)));
}

// `ira serve` prints .../admin/setup#code=XXXX-XXXX-XXXX. The code rides in
// the fragment, which a browser never sends to the server.
export function codeFromHash(hash: string): string {
  const raw = hash.startsWith('#') ? hash.slice(1) : hash;
  return new URLSearchParams(raw).get('code')?.trim() ?? '';
}

const FALLBACK = 'Something went wrong. Try again.';
const UNREACHABLE = 'Cannot reach the server. Check the connection and try again.';

// The server's detail as a sentence: "setup is already done" reads as
// "Setup is already done."
export function sentence(detail: string): string {
  const text = detail.trim();
  if (!text) return FALLBACK;
  const capped = text.charAt(0).toUpperCase() + text.slice(1);
  return /[.!?]$/.test(capped) ? capped : `${capped}.`;
}

// What to tell the person when creating the owner failed.
export function ownerMessage(err: unknown): string {
  if (!(err instanceof ApiError)) return FALLBACK;
  switch (err.status) {
    case 0:
      return UNREACHABLE;
    case 403:
      return 'That setup code is wrong. It is printed where the server runs.';
    case 409:
      return 'Setup is already done. Sign in instead.';
    case 429:
      return 'Too many wrong codes. Try again in 15 minutes.';
    default:
      return sentence(err.detail);
  }
}

export function pinMessage(err: unknown): string {
  if (!(err instanceof ApiError)) return FALLBACK;
  if (err.status === 0) return UNREACHABLE;
  if (err.status === 429) return 'Too many wrong passwords. Try again in 15 minutes.';
  return sentence(err.detail);
}

// What to show next to a control when its request failed.
export function detailOf(err: unknown): string {
  if (err instanceof ApiError) return err.status === 0 ? UNREACHABLE : sentence(err.detail);
  if (err instanceof Error && err.message) return err.message;
  return FALLBACK;
}

// Actions stay locked for a while after wrong PINs; say so when they are.
export function lockedText(status: PinStatus): string | null {
  const left = status.locked_seconds ?? 0;
  if (left <= 0) return null;
  const minutes = Math.max(1, Math.ceil(left / 60));
  return `Actions are locked for another ${minutes} ${minutes === 1 ? 'minute' : 'minutes'} after wrong PINs.`;
}

// What to send for the name and voice: only what changed. A cleared field
// goes back to ira.yaml when it was set here, and is left alone otherwise.
// null means there is nothing to save.
export function settingsUpdate(draft: { name: string; voice: string }, view: SettingsView): SettingsUpdate | null {
  const update: SettingsUpdate = {};
  for (const key of ['name', 'voice'] as const) {
    const setting = view[key];
    if (!setting.editable) continue;
    const value = draft[key].trim();
    const current = setting.value ?? '';
    if (value === current) continue;
    if (value === '') {
      if (setting.overridden) update[key] = null;
      continue;
    }
    update[key] = value;
  }
  return Object.keys(update).length > 0 ? update : null;
}

// Why there is no voice to choose, when there is none.
export function voiceNote(view: SettingsView): string {
  if (!view.tts) {
    return 'Text-to-speech is off, so there is no voice to choose. To add one, set voice.tts in ira.yaml and restart ira serve.';
  }
  return `Text-to-speech uses ${view.tts}; its voice is fixed in ira.yaml.`;
}

// The tier that answers chat, or the first one when none says so.
export function chatTier(models: ModelsView): TierView | null {
  return models.tiers.find((tier) => tier.used_by_assistant) ?? models.tiers[0] ?? null;
}

export function providersInUse(models: ModelsView): ProviderView[] {
  return models.providers.filter((p) => p.in_use);
}

// "fake", or "openai, auth bearer": the type, and the auth when it is one.
export function providerDetail(p: ProviderView): string {
  const parts = [p.type];
  if (p.auth && p.auth !== 'none') parts.push(`auth ${p.auth}`);
  return parts.join(', ');
}

export type KeyState = 'none' | 'set' | 'missing' | 'unknown';

// Whether a provider's key is there, from the provider itself or, failing
// that, from the keys list. Never the value.
export function keyState(provider: ProviderView, keys: readonly KeyView[]): KeyState {
  if (!provider.key_env) return 'none';
  const env = provider.key_env;
  const present = provider.key_present ?? keys.find((k) => k.env === env)?.present ?? null;
  if (present === null) return 'unknown';
  return present ? 'set' : 'missing';
}

// Keys ira.yaml names that no provider in use already accounts for: a voice
// or Telegram key, say.
export function otherKeys(models: ModelsView, keys: readonly KeyView[]): KeyView[] {
  const covered = new Set(providersInUse(models).map((p) => p.key_env).filter(Boolean));
  return keys.filter((k) => !covered.has(k.env));
}

export interface TestLine {
  tone: 'ok' | 'danger';
  text: string;
}

// One line for a model test: ok with the latency, or failed with the reason.
export function testLine(result: ModelTestResult): TestLine {
  if (result.ok) return { tone: 'ok', text: `ok, ${seconds(result.seconds)}` };
  const kind = result.error_kind?.trim() ?? '';
  const error = result.error?.trim() ?? '';
  if (kind && error) return { tone: 'danger', text: `failed: ${error} (${kind})` };
  const why = kind || error;
  return { tone: 'danger', text: why ? `failed: ${why}` : 'failed' };
}

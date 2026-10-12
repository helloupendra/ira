import { describe, expect, it } from 'vitest';
import { ApiError } from '../../api/client';
import type { KeyView, ModelsView, PinStatus, ProviderView, SettingsView, SettingValue, TierView } from '../../api/endpoints';
import {
  chatTier,
  clampStep,
  codeFromHash,
  detailOf,
  keyState,
  lockedText,
  otherKeys,
  ownerMessage,
  parseStep,
  pinMessage,
  providerDetail,
  providersInUse,
  readStep,
  sentence,
  settingsUpdate,
  STEP_KEY,
  testLine,
  voiceNote,
  writeStep,
} from './steps';

class FakeStore {
  items = new Map<string, string>();
  getItem(key: string): string | null {
    return this.items.get(key) ?? null;
  }
  setItem(key: string, value: string): void {
    this.items.set(key, value);
  }
  removeItem(key: string): void {
    this.items.delete(key);
  }
}

const broken = {
  getItem(): string | null {
    throw new Error('blocked');
  },
  setItem(): void {
    throw new Error('blocked');
  },
  removeItem(): void {
    throw new Error('blocked');
  },
};

describe('the remembered step', () => {
  it('reads 2 to 6 and ignores anything else', () => {
    expect(parseStep('3')).toBe(3);
    expect(parseStep(' 6 ')).toBe(6);
    expect(parseStep('1')).toBeNull();
    expect(parseStep('7')).toBeNull();
    expect(parseStep('two')).toBeNull();
    expect(parseStep('')).toBeNull();
    expect(parseStep(null)).toBeNull();
  });

  it('starts at step 2 when nothing is stored', () => {
    expect(readStep(new FakeStore())).toBe(2);
    expect(readStep(null)).toBe(2);
  });

  it('comes back to the step that was written', () => {
    const store = new FakeStore();
    writeStep(4, store);
    expect(store.getItem(STEP_KEY)).toBe('4');
    expect(readStep(store)).toBe(4);
  });

  it('clears the key at the last step', () => {
    const store = new FakeStore();
    writeStep(5, store);
    writeStep(6, store);
    expect(store.getItem(STEP_KEY)).toBeNull();
    expect(readStep(store)).toBe(2);
  });

  it('survives storage that is blocked', () => {
    expect(readStep(broken)).toBe(2);
    expect(() => writeStep(3, broken)).not.toThrow();
    expect(() => writeStep(3, null)).not.toThrow();
  });

  it('keeps a step between 2 and 6', () => {
    expect(clampStep(1)).toBe(2);
    expect(clampStep(9)).toBe(6);
    expect(clampStep(4)).toBe(4);
  });
});

describe('codeFromHash', () => {
  it('reads the code the server printed', () => {
    expect(codeFromHash('#code=7F3A-91C2-0B4E')).toBe('7F3A-91C2-0B4E');
    expect(codeFromHash('code=7F3A-91C2-0B4E')).toBe('7F3A-91C2-0B4E');
    expect(codeFromHash('#code=%207F3A%20')).toBe('7F3A');
  });

  it('is empty without one', () => {
    expect(codeFromHash('')).toBe('');
    expect(codeFromHash('#')).toBe('');
    expect(codeFromHash('#other=1')).toBe('');
  });
});

describe('messages', () => {
  it("turns the server's detail into a sentence", () => {
    expect(sentence('setup is already done; sign in instead')).toBe('Setup is already done; sign in instead.');
    expect(sentence('Done.')).toBe('Done.');
    expect(sentence('  ')).toBe('Something went wrong. Try again.');
  });

  it('says what went wrong with the owner form', () => {
    expect(ownerMessage(new ApiError(403, 'wrong setup code'))).toBe(
      'That setup code is wrong. It is printed where the server runs.',
    );
    expect(ownerMessage(new ApiError(429, 'slow down'))).toBe('Too many wrong codes. Try again in 15 minutes.');
    expect(ownerMessage(new ApiError(409, 'setup is already done'))).toBe('Setup is already done. Sign in instead.');
    expect(ownerMessage(new ApiError(400, 'password must be at least 10 characters'))).toBe(
      'Password must be at least 10 characters.',
    );
    expect(ownerMessage(new ApiError(0, 'Cannot reach the server'))).toBe(
      'Cannot reach the server. Check the connection and try again.',
    );
    expect(ownerMessage(new Error('boom'))).toBe('Something went wrong. Try again.');
  });

  it('says what went wrong with the PIN form', () => {
    expect(pinMessage(new ApiError(429, 'too many wrong passwords'))).toBe(
      'Too many wrong passwords. Try again in 15 minutes.',
    );
    expect(pinMessage(new ApiError(403, 'wrong password'))).toBe('Wrong password.');
    expect(pinMessage(new ApiError(400, 'the PIN must be 4 to 12 digits'))).toBe('The PIN must be 4 to 12 digits.');
    expect(pinMessage('what')).toBe('Something went wrong. Try again.');
  });

  it("shows the server's sentence, else the error, else a fallback", () => {
    expect(detailOf(new ApiError(403, "your role lacks 'admin.write'"))).toBe("Your role lacks 'admin.write'.");
    expect(detailOf(new ApiError(0, 'x'))).toBe('Cannot reach the server. Check the connection and try again.');
    expect(detailOf(new Error('boom'))).toBe('boom');
    expect(detailOf(undefined)).toBe('Something went wrong. Try again.');
  });
});

describe('lockedText', () => {
  const status = (locked: number | null): PinStatus => ({ has_pin: true, can_confirm: true, locked_seconds: locked });

  it('is nothing unless actions are locked', () => {
    expect(lockedText(status(null))).toBeNull();
    expect(lockedText(status(0))).toBeNull();
    expect(lockedText({ has_pin: false, can_confirm: true })).toBeNull();
  });

  it('counts whole minutes, never less than one', () => {
    expect(lockedText(status(900))).toBe('Actions are locked for another 15 minutes after wrong PINs.');
    expect(lockedText(status(61))).toBe('Actions are locked for another 2 minutes after wrong PINs.');
    expect(lockedText(status(5))).toBe('Actions are locked for another 1 minute after wrong PINs.');
  });
});

const setting = (value: string | null, over: Partial<SettingValue> = {}): SettingValue => ({
  value,
  default: 'Ira',
  overridden: false,
  editable: true,
  ...over,
});

const settings = (name: SettingValue, voice: SettingValue, tts: string | null = null): SettingsView => ({
  name,
  voice,
  business: 'Sunrise Dental Clinic, a small dental practice',
  tier: 'default',
  stt: 'fake',
  tts,
});

describe('settingsUpdate', () => {
  it('is nothing when nothing changed', () => {
    const view = settings(setting('Ira'), setting(null, { editable: false, default: null }));
    expect(settingsUpdate({ name: 'Ira', voice: '' }, view)).toBeNull();
    expect(settingsUpdate({ name: ' Ira ', voice: '' }, view)).toBeNull();
  });

  it('sends a new name, trimmed', () => {
    const view = settings(setting('Ira'), setting(null, { editable: false, default: null }));
    expect(settingsUpdate({ name: ' Sunny ', voice: '' }, view)).toEqual({ name: 'Sunny' });
  });

  it('goes back to ira.yaml when a value set here is cleared', () => {
    const view = settings(setting('Sunny', { overridden: true }), setting('Joanna', { overridden: true, default: 'Matthew' }), 'polly');
    expect(settingsUpdate({ name: '', voice: '' }, view)).toEqual({ name: null, voice: null });
  });

  it('leaves a cleared field alone when ira.yaml already decides it', () => {
    const view = settings(setting('Ira'), setting('Joanna', { default: 'Joanna' }), 'polly');
    expect(settingsUpdate({ name: '', voice: 'Joanna' }, view)).toBeNull();
  });

  it('never sends a voice that cannot be edited', () => {
    const view = settings(setting('Ira'), setting(null, { editable: false, default: null }));
    expect(settingsUpdate({ name: 'Ira', voice: 'alloy' }, view)).toBeNull();
  });
});

describe('voiceNote', () => {
  it('explains why there is no voice to choose', () => {
    expect(voiceNote(settings(setting('Ira'), setting(null, { editable: false })))).toMatch(/Text-to-speech is off/);
    expect(voiceNote(settings(setting('Ira'), setting(null, { editable: false }), 'polly'))).toBe(
      'Text-to-speech uses polly; its voice is fixed in ira.yaml.',
    );
  });
});

const tier = (name: string, chain: string[], used = false): TierView => ({
  name,
  configured: chain,
  chain,
  overridden: false,
  used_by_assistant: used,
});

const provider = (over: Partial<ProviderView> = {}): ProviderView => ({
  name: 'demo',
  type: 'fake',
  in_use: true,
  auth: 'none',
  ...over,
});

const models = (tiers: TierView[], providers: ProviderView[]): ModelsView => ({ tiers, providers, cooling: {} });

describe('chatTier', () => {
  it('is the tier that answers chat, else the first, else nothing', () => {
    const fast = tier('fast', ['demo:router']);
    const chat = tier('default', ['openai:gpt-4o-mini'], true);
    expect(chatTier(models([fast, chat], []))).toBe(chat);
    expect(chatTier(models([fast], []))).toBe(fast);
    expect(chatTier(models([], []))).toBeNull();
  });
});

describe('providers and keys', () => {
  const openai = provider({ name: 'openai', type: 'openai', auth: 'bearer', key_env: 'OPENAI_API_KEY', key_present: false });
  const polly = provider({ name: 'polly', type: 'polly', in_use: false, auth: 'sigv4', key_env: 'AWS_SECRET_ACCESS_KEY' });
  const keys: KeyView[] = [
    { env: 'OPENAI_API_KEY', used_by: ['openai'], present: true },
    { env: 'TELEGRAM_BOT_TOKEN', used_by: ['telegram'], present: false },
  ];

  it('lists only the providers in use', () => {
    expect(providersInUse(models([], [provider(), openai, polly])).map((p) => p.name)).toEqual(['demo', 'openai']);
  });

  it('describes a provider by type and auth', () => {
    expect(providerDetail(provider())).toBe('fake');
    expect(providerDetail(openai)).toBe('openai, auth bearer');
  });

  it('knows whether the key is there, without ever seeing it', () => {
    expect(keyState(provider(), keys)).toBe('none');
    expect(keyState(openai, keys)).toBe('missing');
    expect(keyState({ ...openai, key_present: true }, keys)).toBe('set');
    expect(keyState({ ...openai, key_present: null }, keys)).toBe('set');
    expect(keyState({ ...openai, key_present: null }, [])).toBe('unknown');
  });

  it('lists the keys no provider in use accounts for', () => {
    expect(otherKeys(models([], [openai]), keys).map((k) => k.env)).toEqual(['TELEGRAM_BOT_TOKEN']);
    expect(otherKeys(models([], [provider()]), keys).map((k) => k.env)).toEqual(['OPENAI_API_KEY', 'TELEGRAM_BOT_TOKEN']);
  });
});

describe('testLine', () => {
  it('reads ok with the latency', () => {
    expect(testLine({ ref: 'demo:router', ok: true, seconds: 1.234, text: 'Hello.' })).toEqual({
      tone: 'ok',
      text: 'ok, 1.23 s',
    });
  });

  it('reads failed with the reason', () => {
    expect(testLine({ ref: 'x:y', ok: false, seconds: 30, error_kind: 'timeout', error: 'took too long' }).text).toBe(
      'failed: took too long (timeout)',
    );
    expect(testLine({ ref: 'x:y', ok: false, seconds: 0, error_kind: 'auth', error: null }).text).toBe('failed: auth');
    expect(testLine({ ref: 'x:y', ok: false, seconds: 0, error: 'no key' }).text).toBe('failed: no key');
    expect(testLine({ ref: 'x:y', ok: false, seconds: 0 })).toEqual({ tone: 'danger', text: 'failed' });
  });
});

import { ApiError } from '../../api/client';
import type { CoolingReason, ModelTestResult, VoiceOption } from '../../api/endpoints';
import { seconds } from '../../lib/format';

// Moves the item at `index` one step up (-1) or down (+1). The ends stay
// where they are, and the list that came in is never changed.
export function move(order: readonly string[], index: number, delta: -1 | 1): string[] {
  const next = [...order];
  const target = index + delta;
  const a = next[index];
  const b = next[target];
  if (a === undefined || b === undefined) return next;
  next[index] = b;
  next[target] = a;
  return next;
}

export function sameOrder(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((ref, i) => ref === b[i]);
}

// Whole seconds a model still has to wait, counted down from what the server
// said when the page loaded; null once it may be called again.
export function coolingLeft(cooling: Record<string, number>, ref: string, elapsed: number): number | null {
  const total = cooling[ref];
  if (total === undefined) return null;
  const left = Math.ceil(total - Math.max(0, elapsed));
  return left > 0 ? left : null;
}

// Why a model is cooling, on one line: the error's kind, then the server's
// own sentence. The HTTP status goes in when there is one and the sentence
// does not already name it (the server usually folds it in itself).
export function coolingNote(reason: CoolingReason): string {
  const kind = reason.error_kind.trim();
  let message = reason.message.trim();
  const status = reason.status ?? 0;
  if (status > 0 && !message.includes(`HTTP ${status}`)) {
    const stop = message.endsWith('.');
    const head = stop ? message.slice(0, -1) : message;
    message = `${head}${head ? ' ' : ''}(HTTP ${status})${stop ? '.' : ''}`;
  }
  return [kind, message].filter(Boolean).join(': ');
}

// What a voice's suggestion says next to its id: the languages it speaks and
// its gender, as far as the provider says; empty when it says nothing.
export function voiceLabel(voice: VoiceOption): string {
  return [...voice.languages, voice.gender ?? '']
    .map((part) => part.trim())
    .filter(Boolean)
    .join(', ');
}

export interface TestLine {
  tone: 'ok' | 'danger';
  text: string;
  detail: string | null;
}

// The one-line verdict of a model test, plus the reply (when there was one)
// to show more quietly after it.
export function testLine(result: ModelTestResult): TestLine {
  if (result.ok) {
    const reply = result.text?.trim() ?? '';
    return { tone: 'ok', text: `ok, ${seconds(result.seconds)}`, detail: reply || null };
  }
  const why = [result.error_kind, result.error]
    .map((part) => part?.trim() ?? '')
    .filter(Boolean)
    .join(' ');
  return { tone: 'danger', text: why ? `failed: ${why}` : 'failed', detail: null };
}

// What to show next to a control when its request failed.
export function detailOf(err: unknown): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof Error && err.message) return err.message;
  return 'Something went wrong.';
}

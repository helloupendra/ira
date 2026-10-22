import type { DeviceView, GrantView } from '../../api/endpoints';
import { ago } from '../../lib/format';

// A tool's tier in a few words: what Ira needs from you before it runs.
const TIER_WORDS = ['reads', 'small change', 'needs your yes', 'needs your PIN'];

export function tierWord(tier: number): string {
  return TIER_WORDS[tier] ?? `tier ${tier}`;
}

export function kindWord(kind: string): string {
  if (kind === 'mac') return 'Mac';
  if (kind === 'android') return 'Android phone';
  return kind;
}

// "Connected", or when the device was last heard from.
export function statusOf(
  device: Pick<DeviceView, 'connected' | 'last_seen_at'>,
  now: number = Date.now() / 1000,
): { label: string; tone: 'ok' | 'muted' } {
  if (device.connected) return { label: 'Connected', tone: 'ok' };
  if (!device.last_seen_at) return { label: 'Never connected', tone: 'muted' };
  return { label: `Last seen ${ago(device.last_seen_at, now)}`, tone: 'muted' };
}

// The whole list of skills a device should have after one switch changes.
export function skillsAfter(device: Pick<DeviceView, 'skills'>, name: string, on: boolean): string[] {
  const current = device.skills.filter((s) => s.on).map((s) => s.name);
  if (on) return current.includes(name) ? current : [...current, name];
  return current.filter((s) => s !== name);
}

// Minutes and seconds left on a pairing code, or "expired".
export function remaining(expiresAt: number, now: number = Date.now() / 1000): string {
  const left = Math.max(0, Math.round(expiresAt - now));
  if (left === 0) return 'expired';
  const m = Math.floor(left / 60);
  const s = left % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

// What a grant allows, as a heading: "chrome on Studio Mac", "Web and news search".
export function grantTitle(grant: Pick<GrantView, 'kind' | 'skill' | 'device'>): string {
  if (grant.kind === 'web_search') return 'Web and news search';
  const skill = grant.skill.charAt(0).toUpperCase() + grant.skill.slice(1);
  return `${skill} on ${grant.device ?? 'a device'}`;
}

// How to set up each kind of device, in order.
export function setupSteps(kind: string): string[] {
  if (kind === 'mac') {
    return [
      'Download the Ira companion for Mac and open the zip.',
      'In Terminal, run: cd ~/Downloads/ira-mac && ./install.sh',
      'When it asks, paste the pairing link (or type the code).',
      'In Chrome, open chrome://extensions, switch on Developer mode, click Load unpacked, and choose the folder the installer names.',
      'Ask Ira: "Chrome mein kaunse tabs khule hain?"',
    ];
  }
  return ['Open the Ira app on the phone and scan the QR code.'];
}

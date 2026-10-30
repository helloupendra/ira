import { describe, expect, it } from 'vitest';
import { grantTitle, kindWord, remaining, setupSteps, skillsAfter, statusOf, tierWord } from './text';

const NOW = Date.UTC(2026, 9, 22, 10, 0) / 1000;

describe('statusOf', () => {
  it('says connected, last seen or never', () => {
    expect(statusOf({ connected: true, last_seen_at: null }, NOW)).toEqual({ label: 'Connected', tone: 'ok' });
    expect(statusOf({ connected: false, last_seen_at: NOW - 300 }, NOW).label).toBe('Last seen 5 min ago');
    expect(statusOf({ connected: false, last_seen_at: null }, NOW).label).toBe('Never connected');
  });
});

describe('skillsAfter', () => {
  const device = {
    skills: [
      { name: 'browser', description: '', on: true, offered: true },
      { name: 'tasks', description: '', on: false, offered: false },
    ],
  };
  it('adds or drops one skill and keeps the rest', () => {
    expect(skillsAfter(device, 'tasks', true)).toEqual(['browser', 'tasks']);
    expect(skillsAfter(device, 'browser', false)).toEqual([]);
    expect(skillsAfter(device, 'browser', true)).toEqual(['browser']);
  });
});

describe('words', () => {
  it('reads tiers, kinds, grants and time left', () => {
    expect(tierWord(0)).toBe('reads');
    expect(tierWord(3)).toBe('needs your PIN');
    expect(tierWord(9)).toBe('tier 9');
    expect(kindWord('android')).toBe('Android phone');
    expect(kindWord('ios')).toBe('iPhone');
    expect(setupSteps('ios').join(' ')).toContain('Ira for iPhone');
    expect(kindWord('windows')).toBe('Windows PC');
    expect(setupSteps('windows').join(' ')).toContain('Ira for Windows');
    expect(grantTitle({ kind: 'device_skill', skill: 'browser', device: 'Studio Mac' })).toBe('Browser on Studio Mac');
    expect(grantTitle({ kind: 'web_search', skill: 'web', device: null })).toBe('Web and news search');
    expect(remaining(NOW + 598, NOW)).toBe('9:58');
    expect(remaining(NOW - 1, NOW)).toBe('expired');
    expect(setupSteps('mac')[0]).toContain('Ira for Mac');
    expect(setupSteps('mac').join(' ')).not.toContain('install.sh');
  });
});

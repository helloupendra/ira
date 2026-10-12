import { describe, expect, it } from 'vitest';
import type { CostDay } from '../../api/endpoints';
import { dayDate } from '../../lib/format';
import {
  byDayDesc,
  changeWords,
  dayEpoch,
  hrefFor,
  okLabel,
  totals,
  triedLine,
  viaLine,
  viewFromSearch,
} from './text';

process.env.TZ = 'UTC';

function day(partial: Partial<CostDay> = {}): CostDay {
  return { day: '2026-10-12', calls: 10, failures: 1, cost_usd: 0.25, input_tokens: 1000, output_tokens: 200, ...partial };
}

describe('the view chips', () => {
  it('read the query string, with changes as the default', () => {
    expect(viewFromSearch('view=cost')).toBe('cost');
    expect(viewFromSearch('?view=actions&x=1')).toBe('actions');
    expect(viewFromSearch('view=Cost')).toBe('cost');
    expect(viewFromSearch('')).toBe('changes');
    expect(viewFromSearch('view=nothing')).toBe('changes');
  });
  it('write it back the same way', () => {
    expect(hrefFor('changes')).toBe('/audit');
    expect(hrefFor('actions')).toBe('/audit?view=actions');
    expect(hrefFor('cost')).toBe('/audit?view=cost');
  });
});

describe('changeWords', () => {
  it('turns dots and underscores into spaces', () => {
    expect(changeWords('tool.enabled')).toBe('tool enabled');
    expect(changeWords('user.invite_withdrawn')).toBe('user invite withdrawn');
    expect(changeWords('settings.updated')).toBe('settings updated');
  });
});

describe('dayEpoch', () => {
  it('parses a day as local midnight', () => {
    const epoch = dayEpoch('2026-10-12');
    expect(epoch).toBe(Date.UTC(2026, 9, 12) / 1000);
    expect(dayDate(epoch ?? 0)).toBe('Mon 12 Oct 2026');
  });
  it('rejects anything that is not a real date', () => {
    expect(dayEpoch('2026-02-30')).toBeNull();
    expect(dayEpoch('today')).toBeNull();
    expect(dayEpoch('')).toBeNull();
  });
});

describe('cost days', () => {
  it('sort newest first', () => {
    const rows = [day({ day: '2026-10-10' }), day({ day: '2026-10-12' }), day({ day: '2026-10-11' })];
    expect(byDayDesc(rows).map((r) => r.day)).toEqual(['2026-10-12', '2026-10-11', '2026-10-10']);
    expect(rows[0]?.day).toBe('2026-10-10');
  });
  it('add up to the totals', () => {
    const sum = totals([day(), day({ day: '2026-10-11', calls: 5, failures: 0, cost_usd: 0.5, input_tokens: 1, output_tokens: 2 })]);
    expect(sum).toEqual({ calls: 15, failures: 1, cost_usd: 0.75, input_tokens: 1001, output_tokens: 202 });
    expect(totals([])).toEqual({ calls: 0, failures: 0, cost_usd: 0, input_tokens: 0, output_tokens: 0 });
  });
});

describe('a model call', () => {
  it('reads ok, or names the error', () => {
    expect(okLabel({ ok: true, error_kind: null })).toBe('ok');
    expect(okLabel({ ok: false, error_kind: 'timeout' })).toBe('timeout');
    expect(okLabel({ ok: false, error_kind: 'rate_limited' })).toBe('rate limited');
    expect(okLabel({ ok: false, error_kind: null })).toBe('failed');
  });
  it('lists what was tried only when it took more than one attempt', () => {
    expect(triedLine({ tried: 'demo:router', attempts: 1, model: 'demo:router' })).toBeNull();
    expect(triedLine({ tried: 'openai:gpt-4o-mini,demo:router', attempts: 2, model: 'demo:router' })).toBe(
      'tried: openai:gpt-4o-mini, demo:router (2 attempts)',
    );
    expect(triedLine({ tried: 'a, b, c', attempts: 3, model: 'c' })).toBe('tried: a, b, c (3 attempts)');
    expect(triedLine({ tried: '', attempts: 2, model: null })).toBe('tried: none (2 attempts)');
  });
});

describe('viaLine', () => {
  it('does not repeat a channel the actor already names', () => {
    expect(viaLine('owner@example.com via web', 'web')).toBe('owner@example.com via web');
    expect(viaLine('owner@example.com', 'telegram')).toBe('owner@example.com via telegram');
    expect(viaLine('owner@example.com', null)).toBe('owner@example.com');
  });
  it('says when nothing was recorded', () => {
    expect(viaLine(null, 'cli')).toBe('someone via cli');
    expect(viaLine(null, null)).toBe('not recorded');
    expect(viaLine('  ', '')).toBe('not recorded');
  });
});

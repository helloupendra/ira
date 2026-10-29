import { describe, expect, it } from 'vitest';
import { ago, clock, costText, count, dayDate, humanize, pct, seconds, usd, when } from './format';

// Node applies a change to TZ at once; the formatters are built per call.
process.env.TZ = 'UTC';

// Monday 12 October 2026, 14:32 UTC.
const T = Date.UTC(2026, 9, 12, 14, 32) / 1000;

describe('costText', () => {
  it('says unknown, never $0, when a cost is not known', () => {
    expect(costText(null)).toBe('unknown');
    expect(costText(0)).toBe('$0.00');
    expect(costText(0.12, 3)).toBe('$0.12 + 3 unknown');
  });
});

describe('usd', () => {
  it('uses two decimals from one cent up', () => {
    expect(usd(1.23)).toBe('$1.23');
    expect(usd(0.01)).toBe('$0.01');
    expect(usd(1234.5)).toBe('$1,234.50');
  });
  it('uses four decimals below one cent', () => {
    expect(usd(0.0042)).toBe('$0.0042');
    expect(usd(0.009)).toBe('$0.0090');
  });
  it('shows zero and nothing plainly', () => {
    expect(usd(0)).toBe('$0.00');
    expect(usd(null)).toBe('–');
  });
});

describe('seconds', () => {
  it('formats with two decimals and a unit', () => {
    expect(seconds(1.84)).toBe('1.84 s');
    expect(seconds(0)).toBe('0.00 s');
    expect(seconds(12.3456)).toBe('12.35 s');
  });
  it('shows a dash for null', () => {
    expect(seconds(null)).toBe('–');
  });
});

describe('count and pct', () => {
  it('groups thousands', () => {
    expect(count(0)).toBe('0');
    expect(count(11221)).toBe('11,221');
    expect(count(1234567)).toBe('1,234,567');
  });
  it('turns a fraction into a percentage', () => {
    expect(pct(0.1234)).toBe('12.3%');
    expect(pct(1)).toBe('100%');
    expect(pct(0)).toBe('0%');
  });
});

describe('dates', () => {
  it('clock', () => {
    expect(clock(T)).toBe('14:32');
    expect(clock(Date.UTC(2026, 9, 12, 0, 5) / 1000)).toBe('00:05');
  });
  it('dayDate', () => {
    expect(dayDate(T)).toBe('Mon 12 Oct 2026');
  });
  it('when: the time alone today, the day otherwise', () => {
    expect(when(T, T + 3600)).toBe('14:32');
    expect(when(T, T + 86400)).toBe('12 Oct, 14:32');
  });
  it('ago', () => {
    expect(ago(T, T + 10)).toBe('just now');
    expect(ago(T, T + 240)).toBe('4 min ago');
    expect(ago(T, T + 7200)).toBe('2 h ago');
    expect(ago(T, T + 3 * 86400)).toBe('3 d ago');
    expect(ago(T + 50, T)).toBe('just now');
  });
});

describe('humanize', () => {
  it('turns underscores into spaces', () => {
    expect(humanize('find_slots')).toBe('find slots');
    expect(humanize('book_appointment')).toBe('book appointment');
    expect(humanize('plain')).toBe('plain');
  });
});

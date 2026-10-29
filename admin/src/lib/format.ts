// Every number and date on the console goes through here, so they all read
// the same way. The locale is fixed so the output does not depend on the
// machine, and formatters are made on demand so a test can set the time zone.

const LOCALE = 'en-GB';
const DASH = '–';

function number(n: number, min: number, max: number): string {
  return new Intl.NumberFormat(LOCALE, {
    minimumFractionDigits: min,
    maximumFractionDigits: max,
  }).format(n);
}

function dateParts(epoch: number, options: Intl.DateTimeFormatOptions): Record<string, string> {
  const parts: Record<string, string> = {};
  for (const part of new Intl.DateTimeFormat(LOCALE, options).formatToParts(new Date(epoch * 1000))) {
    parts[part.type] = part.value;
  }
  return parts;
}

function isMissing(n: number | null | undefined): n is null | undefined {
  return n === null || n === undefined || !Number.isFinite(n);
}

// Cost in US dollars as the API reports it. Below one cent, four decimals
// keep tiny per-call costs from reading as free.
export function usd(n: number | null | undefined): string {
  if (isMissing(n)) return DASH;
  const digits = n !== 0 && Math.abs(n) < 0.01 ? 4 : 2;
  return `$${number(n, digits, digits)}`;
}

// A cost that may not be known: one call's ("unknown" when it is not), or a total with
// how many of its calls have no known cost ("$0.12 + 3 unknown"). Never $0 for unknown.
export function costText(n: number | null | undefined, unknown = 0): string {
  if (isMissing(n)) return 'unknown';
  return unknown > 0 ? `${usd(n)} + ${count(unknown)} unknown` : usd(n);
}

export function seconds(n: number | null | undefined): string {
  if (isMissing(n)) return DASH;
  return `${number(n, 2, 2)} s`;
}

export function count(n: number | null | undefined): string {
  if (isMissing(n)) return DASH;
  return number(n, 0, 0);
}

// A fraction (0.123) as a percentage ("12.3%").
export function pct(fraction: number | null | undefined): string {
  if (isMissing(fraction)) return DASH;
  return `${number(fraction * 100, 0, 1)}%`;
}

export function clock(epoch: number): string {
  const p = dateParts(epoch, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
  return `${p.hour}:${p.minute}`;
}

export function dayDate(epoch: number): string {
  const p = dateParts(epoch, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
  return `${p.weekday} ${p.day} ${p.month} ${p.year}`;
}

function sameDay(a: number, b: number): boolean {
  const da = new Date(a * 1000);
  const db = new Date(b * 1000);
  return (
    da.getFullYear() === db.getFullYear() &&
    da.getMonth() === db.getMonth() &&
    da.getDate() === db.getDate()
  );
}

// The time alone when it happened today, otherwise the day as well.
export function when(epoch: number, now: number = Date.now() / 1000): string {
  if (sameDay(epoch, now)) return clock(epoch);
  const p = dateParts(epoch, { day: 'numeric', month: 'short' });
  return `${p.day} ${p.month}, ${clock(epoch)}`;
}

export function ago(epoch: number, now: number = Date.now() / 1000): string {
  const diff = Math.max(0, now - epoch);
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  return `${Math.floor(diff / 86400)} d ago`;
}

// A tool name as words: "find_slots" reads as "find slots".
export function humanize(name: string): string {
  return name.replace(/[_\s]+/g, ' ').trim();
}

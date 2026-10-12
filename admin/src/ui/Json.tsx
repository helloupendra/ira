// Parameters, results and other structured values, pretty-printed. Strings
// that are JSON themselves (a tool result stored as text) are unpacked.
export function pretty(value: unknown): string {
  if (typeof value === 'string') {
    try {
      return JSON.stringify(JSON.parse(value), null, 2);
    } catch {
      return value;
    }
  }
  if (value === undefined) return '';
  return JSON.stringify(value, null, 2) ?? '';
}

export function Json({ value, compact = false }: { value: unknown; compact?: boolean }) {
  const text = pretty(value);
  if (!text) return <span className="muted">none</span>;
  return <pre className={compact ? 'json json-compact' : 'json'}>{text}</pre>;
}

// Where the next page starts: the last row's time and id, so actions proposed
// at the same moment are neither skipped nor repeated.
export interface Cursor {
  before: number;
  before_id: string;
}

interface Row {
  id: string;
  created_at: number;
}

export function cursorAfter(rows: readonly Row[]): Cursor | null {
  const last = rows[rows.length - 1];
  return last ? { before: last.created_at, before_id: last.id } : null;
}

// A page's rows minus any already on screen, so a row never appears twice.
export function withoutRepeats<T extends { id: string }>(shown: readonly T[], page: readonly T[]): T[] {
  const seen = new Set(shown.map((row) => row.id));
  return page.filter((row) => !seen.has(row.id));
}

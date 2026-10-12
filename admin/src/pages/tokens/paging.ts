// The cursor a session list pages with, read from its last row.
export interface Cursor {
  before: number;
  before_id: string;
}

interface SessionLike {
  id: string;
  created_at: number;
  last_used_at: number | null;
}

// Where the next page starts. The server orders sessions by their last use,
// falling back to sign-in for one never used since, so the cursor does too.
export function cursorAfter<T extends SessionLike>(rows: readonly T[]): Cursor | null {
  const last = rows[rows.length - 1];
  if (!last) return null;
  return { before: last.last_used_at ?? last.created_at, before_id: last.id };
}

// The rows of a page that are not on the list yet. A session used between
// two page loads can move up and arrive twice; it is shown once.
export function newRows<T extends { id: string }>(have: readonly T[], page: readonly T[]): T[] {
  const seen = new Set(have.map((row) => row.id));
  return page.filter((row) => !seen.has(row.id));
}

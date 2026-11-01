// Sign-ins from the same device (and, in everyone's list, the same person) shown as
// one row: a script that signs in every run would otherwise fill the page with
// identical lines. This device's own session always stands alone.

export interface SessionLike {
  id: string;
  current: boolean;
  created_at: number;
  last_used_at?: number | null;
  expires_at: number;
}

export interface SessionGroup<T> {
  key: string;
  rows: T[];
}

/** Groups in the order their first session came; a group of one is a plain row. */
export function groupSessions<T extends SessionLike>(rows: readonly T[], keyOf: (row: T) => string): SessionGroup<T>[] {
  const groups: SessionGroup<T>[] = [];
  const byKey = new Map<string, SessionGroup<T>>();
  for (const row of rows) {
    if (row.current) {
      groups.push({ key: `current:${row.id}`, rows: [row] });
      continue;
    }
    const key = keyOf(row);
    let group = byKey.get(key);
    if (!group) {
      group = { key, rows: [] };
      byKey.set(key, group);
      groups.push(group);
    }
    group.rows.push(row);
  }
  return groups;
}

/** What a group's row shows: its newest sign-in, its latest use and its last expiry. */
export function groupSpan(rows: readonly SessionLike[]): {
  newest: number;
  oldest: number;
  lastUsed: number | null;
  expires: number;
} {
  const created = rows.map((row) => row.created_at);
  const used = rows.map((row) => row.last_used_at).filter((at): at is number => typeof at === 'number');
  return {
    newest: Math.max(...created),
    oldest: Math.min(...created),
    lastUsed: used.length ? Math.max(...used) : null,
    expires: Math.max(...rows.map((row) => row.expires_at)),
  };
}

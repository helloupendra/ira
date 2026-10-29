import { describe, expect, it } from 'vitest';
import type { ActionCounts, ActionRow, ToolDetail } from '../../api/endpoints';
import {
  countFor,
  emptyText,
  hrefFor,
  labelFor,
  listRoles,
  outcomeLine,
  proposedBy,
  statusFromSearch,
  whoMayConfirm,
} from './text';

process.env.TZ = 'UTC';

// Monday 12 October 2026, 14:32 UTC.
const T = Date.UTC(2026, 9, 12, 14, 32) / 1000;

function row(partial: Partial<ActionRow> = {}): ActionRow {
  return {
    id: 'act_1',
    tool: 'cancel_appointment',
    params: { id: 17 },
    summary: 'Cancel appointment #17',
    conversation_id: 'http:1:abc',
    channel: 'web',
    actor: 'owner@example.com',
    created_at: T,
    expires_at: T + 120,
    status: 'pending',
    result: null,
    finished_at: null,
    decided_by: null,
    decided_channel: null,
    decided_at: null,
    ...partial,
  };
}

function tool(partial: Partial<ToolDetail> = {}): ToolDetail {
  return {
    name: 'cancel_appointment',
    kind: 'action',
    description: '',
    parameters: {},
    enabled: true,
    confirm_roles: ['owner', 'admin', 'staff'],
    ...partial,
  };
}

const COUNTS: ActionCounts = {
  since: null,
  total: 29,
  pending: 0,
  executing: 1,
  executed: 2,
  failed: 1,
  unknown: 0,
  cancelled: 1,
  expired: 24,
};

describe('the status filter', () => {
  it('reads the query string with or without the question mark', () => {
    expect(statusFromSearch('status=pending')).toBe('pending');
    expect(statusFromSearch('?status=failed&x=1')).toBe('failed');
    expect(statusFromSearch('')).toBe('');
    expect(statusFromSearch('other=1')).toBe('');
  });
  it('writes it back the same way', () => {
    expect(hrefFor('')).toBe('/actions');
    expect(hrefFor('pending')).toBe('/actions?status=pending');
    expect(hrefFor('a b')).toBe('/actions?status=a%20b');
  });
  it('labels a status that has no chip', () => {
    expect(labelFor('executing')).toBe('Executing');
    expect(labelFor('on_hold')).toBe('On hold');
  });
});

describe('countFor', () => {
  it('gives every chip its number, and All the total', () => {
    expect(countFor(COUNTS, '')).toBe(29);
    expect(countFor(COUNTS, 'pending')).toBe(0);
    expect(countFor(COUNTS, 'executing')).toBe(1);
    expect(countFor(COUNTS, 'executed')).toBe(2);
    expect(countFor(COUNTS, 'failed')).toBe(1);
    expect(countFor(COUNTS, 'expired')).toBe(24);
    expect(countFor(COUNTS, 'cancelled')).toBe(1);
  });
  it('has nothing before the counts arrive, or for a status the server does not count', () => {
    expect(countFor(undefined, '')).toBeNull();
    expect(countFor(COUNTS, 'on_hold')).toBeNull();
  });
});

describe('emptyText', () => {
  it('names the filter', () => {
    expect(emptyText('')).toBe(
      'No actions yet. When Ira proposes a change it appears here with its outcome.',
    );
    expect(emptyText('pending')).toBe('No pending actions.');
    expect(emptyText('executed')).toBe('No executed actions yet.');
    expect(emptyText('failed')).toBe('No failed actions.');
    expect(emptyText('expired')).toBe('No expired actions.');
    expect(emptyText('cancelled')).toBe('No cancelled actions.');
    expect(emptyText('executing')).toBe('No executing actions.');
  });
});

describe('proposedBy', () => {
  it('names the person and the channel', () => {
    expect(proposedBy('owner@example.com', 'web')).toBe('owner@example.com via web');
    expect(proposedBy('staff@example.com', 'telegram')).toBe('staff@example.com via telegram');
  });
  it('copes with missing pieces', () => {
    expect(proposedBy('owner@example.com', null)).toBe('owner@example.com');
    expect(proposedBy(null, 'web')).toBe('someone via web');
    expect(proposedBy(null, null)).toBe('not recorded');
    expect(proposedBy('  ', '')).toBe('not recorded');
  });
});

describe('whoMayConfirm', () => {
  it('lists the roles as words', () => {
    expect(listRoles(['owner'])).toBe('owner');
    expect(listRoles(['owner', 'admin'])).toBe('owner or admin');
    expect(listRoles(['owner', 'admin', 'staff'])).toBe('owner, admin or staff');
    expect(listRoles([])).toBe('');
  });
  it('says where the roles come from', () => {
    expect(whoMayConfirm(tool())).toBe('owner, admin or staff (set in ira.yaml)');
    expect(whoMayConfirm(tool({ confirm_roles: ['owner'] }))).toBe('owner (set in ira.yaml)');
  });
  it('explains an unknown or changed tool', () => {
    expect(whoMayConfirm(undefined)).toBe('the tool is no longer registered');
    expect(whoMayConfirm(tool({ confirm_roles: [] }))).toBe('no one (no roles are set in ira.yaml)');
    expect(whoMayConfirm(tool({ kind: 'read', confirm_roles: null }))).toBe(
      'no one: the tool no longer asks for confirmation',
    );
  });
});

describe('outcomeLine', () => {
  it('shows when a pending action runs out, and leaves expiring to the server', () => {
    expect(outcomeLine(row(), T)).toEqual({ label: 'Expires at', text: '14:34' });
    expect(outcomeLine(row(), T + 300)).toEqual({ label: 'Expires at', text: '14:34' });
  });
  it('shows when an expired action ran out', () => {
    expect(outcomeLine(row({ status: 'expired' }), T + 300)).toEqual({ label: 'Expired at', text: '14:34' });
    expect(outcomeLine(row({ status: 'expired' }), T + 86400)).toEqual({
      label: 'Expired at',
      text: '12 Oct, 14:34',
    });
  });
  it('says who decided, where, and when', () => {
    const done = row({
      status: 'executed',
      decided_by: 'owner@example.com',
      decided_channel: 'web',
      decided_at: T + 60,
      finished_at: T + 61,
    });
    expect(outcomeLine(done, T + 100)).toEqual({
      label: 'Decided by',
      text: 'owner@example.com via web at 14:33',
    });
    expect(outcomeLine(row({ ...done, decided_channel: null }), T + 100)).toEqual({
      label: 'Decided by',
      text: 'owner@example.com at 14:33',
    });
    expect(outcomeLine(row({ ...done, decided_at: null }), T + 100)).toEqual({
      label: 'Decided by',
      text: 'owner@example.com via web',
    });
    expect(outcomeLine(row({ ...done, decided_channel: null, decided_at: null }), T + 100)).toEqual({
      label: 'Decided by',
      text: 'owner@example.com',
    });
  });
  it('falls back when the audit log has less', () => {
    expect(
      outcomeLine(row({ status: 'cancelled', decided_channel: 'telegram', decided_at: T + 60 }), T + 100),
    ).toEqual({ label: 'Decided', text: 'via telegram at 14:33' });
    expect(outcomeLine(row({ status: 'cancelled', decided_at: T + 60 }), T + 100)).toEqual({
      label: 'Decided at',
      text: '14:33',
    });
    expect(outcomeLine(row({ status: 'failed', finished_at: T + 5 }), T)).toEqual({
      label: 'Finished at',
      text: '14:32',
    });
    expect(outcomeLine(row({ status: 'failed' }), T)).toBeNull();
  });
});
